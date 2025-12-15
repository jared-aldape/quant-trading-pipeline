import sys
import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import engine_forensics as forensics

log = get_logger("BacktestEngine")
TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# 2. HELPER: DATABASE WRITER (TZ CORRECTED)
# ==============================================================================
def save_simulation_to_db(trades):
    """
    Commits the generated trade list to active_simulation_log.
    CRITICAL: Converts Naive PST Strings -> UTC Timestamps before saving.
    """
    if not trades: return
    if not config.DB_FILE.exists(): return

    con = duckdb.connect(str(config.DB_FILE))
    
    try:
        # 1. CHECK SCHEMA (Auto-Migration Logic)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        
        schema_sql = """
            CREATE TABLE active_simulation_log (
                entry_time TIMESTAMP,
                exit_time TIMESTAMP,
                ticker VARCHAR,
                entry_price DOUBLE,
                exit_price DOUBLE,
                quantity INTEGER,
                net_pnl DOUBLE,
                return_pct DOUBLE,
                reason VARCHAR,
                status VARCHAR,
                notes VARCHAR,
                meta_data VARCHAR
            )
        """
        
        if 'active_simulation_log' not in tables:
            con.execute(schema_sql)
        else:
            col_count = len(con.execute("DESCRIBE active_simulation_log").fetchall())
            if col_count != 12:
                log.warning(f"Schema Mismatch (Found {col_count} cols). Re-initializing...")
                con.execute("DROP TABLE active_simulation_log")
                con.execute(schema_sql)

        # 2. Wipe Previous Data Generator Records
        con.execute("DELETE FROM active_simulation_log WHERE reason = 'DATA_GENERATOR'")
        
        # 3. Format Data (TZ NORMALIZATION)
        db_rows = []
        for t in trades:
            # Reconstruct Naive PST Timestamp from Strings
            str_entry = f"{t['Date']} {t['Entry_Time']}"
            str_exit = f"{t['Date']} {t['Exit_Time']}"
            
            # Localize to PST, then Convert to UTC
            # This is critical so the Mirror (which expects UTC) plots it correctly
            ts_entry = pd.to_datetime(str_entry).tz_localize(TZ_PST).tz_convert(TZ_UTC).tz_localize(None)
            ts_exit = pd.to_datetime(str_exit).tz_localize(TZ_PST).tz_convert(TZ_UTC).tz_localize(None)
            
            db_rows.append((
                ts_entry,
                ts_exit,
                t['Ticker'],
                float(t.get('Raw_Entry', 1.0)),
                float(t.get('Raw_Exit', 1.0)),
                5, 
                float(t.get('Raw_PnL', 0.0)),
                float(t.get('Raw_Ret', 0.0)),
                'DATA_GENERATOR', 
                'CLOSED',         
                f"Dur: {t['Duration']}", 
                '{"source": "algo_v3_rth"}' 
            ))
            
        # 4. Insert
        con.executemany("""
            INSERT INTO active_simulation_log 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, db_rows)
        
        log.info(f"💾 SAVED {len(db_rows)} TRADES TO DB (UTC NORMALIZED)")
        
    except Exception as e:
        log.error(f"DB Save Error: {e}")
    finally:
        con.close()

# ==============================================================================
# 3. THE VIG
# ==============================================================================
def calculate_friction(num_contracts, price, model="RH_GOLD"):
    if model == "LIVE_REALITY": return 0.0
    reg_fee = num_contracts * 0.03
    comm = 0.0
    if model == "STD": comm = num_contracts * 0.65
    elif model == "PROP": comm = num_contracts * 1.50
    slippage = num_contracts * 1.00 
    return reg_fee + comm + slippage

# ==============================================================================
# 4. TRADE SIMULATOR
# ==============================================================================
def get_trade_outcome(con, signal, params):
    # 1. Timezone Conversion (UTC -> PST)
    entry_utc = pd.to_datetime(signal['entry_timestamp_utc'], unit='ms').replace(tzinfo=TZ_UTC)
    entry_pst = entry_utc.astimezone(TZ_PST)
    
    rth_open = time(6, 30)
    rth_cutoff = time(12, 55)
    if not (rth_open <= entry_pst.time() <= rth_cutoff):
        return None 

    # 2. Parse Params
    target_pct = float(params.get('ideal_gain', 30)) / 100.0
    stop_pct = float(params.get('max_loss', 50)) / 100.0
    trail_pct = float(params.get('trail_stop', 15)) / 100.0
    
    leverage = 80.0
    idx_target_dist = target_pct / leverage
    idx_stop_dist = stop_pct / leverage
    idx_trail_dist = trail_pct / leverage
    
    # 3. Fetch Market Data
    eod_pst = entry_pst.replace(hour=13, minute=0, second=0, microsecond=0)
    eod_utc = eod_pst.astimezone(TZ_UTC)
    
    start_str = entry_utc.strftime('%Y-%m-%d %H:%M:%S')
    end_str = eod_utc.strftime('%Y-%m-%d %H:%M:%S')
    
    ticker = 'XSP'
    q = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker='{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
    df_mkt = con.execute(q).df()
    
    if df_mkt.empty:
        ticker = 'SPX'
        q = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker='{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
        df_mkt = con.execute(q).df()
        
    if df_mkt.empty: return None 

    # 4. Simulation
    entry_px = df_mkt.iloc[0]['open']
    trade_type = signal['trade_type'].upper()
    is_call = 'CALL' in trade_type or 'BULL' in trade_type
    
    if is_call:
        take_profit_px = entry_px * (1 + idx_target_dist)
        hard_stop_px = entry_px * (1 - idx_stop_dist)
        highest_px = entry_px
    else: 
        take_profit_px = entry_px * (1 - idx_target_dist)
        hard_stop_px = entry_px * (1 + idx_stop_dist)
        lowest_px = entry_px

    exit_px = df_mkt.iloc[-1]['close']
    exit_utc = df_mkt.iloc[-1]['datetime_utc'].replace(tzinfo=TZ_UTC)
    status = "EOD_EXIT"
    
    for _, candle in df_mkt.iterrows():
        current_time_utc = candle['datetime_utc'].replace(tzinfo=TZ_UTC)
        
        if is_call:
            if candle['high'] >= take_profit_px:
                exit_px = take_profit_px
                exit_utc = current_time_utc
                status = "IDEAL_GAIN"
                break
            if candle['low'] <= hard_stop_px:
                exit_px = hard_stop_px
                exit_utc = current_time_utc
                status = "MAX_LOSS"
                break
            if candle['high'] > highest_px: highest_px = candle['high']
            trail_stop_px = highest_px * (1 - idx_trail_dist)
            if candle['low'] <= max(hard_stop_px, trail_stop_px):
                exit_px = max(hard_stop_px, trail_stop_px)
                exit_utc = current_time_utc
                status = "TRAILING_STOP"
                break
        else: # PUT
            if candle['low'] <= take_profit_px:
                exit_px = take_profit_px
                exit_utc = current_time_utc
                status = "IDEAL_GAIN"
                break
            if candle['high'] >= hard_stop_px:
                exit_px = hard_stop_px
                exit_utc = current_time_utc
                status = "MAX_LOSS"
                break
            if candle['low'] < lowest_px: lowest_px = candle['low']
            trail_stop_px = lowest_px * (1 + idx_trail_dist)
            if candle['high'] >= min(hard_stop_px, trail_stop_px):
                exit_px = min(hard_stop_px, trail_stop_px)
                exit_utc = current_time_utc
                status = "TRAILING_STOP"
                break
    
    # 6. Metrics
    if is_call: idx_ret = (exit_px - entry_px) / entry_px
    else: idx_ret = (entry_px - exit_px) / entry_px
        
    opt_ret = idx_ret * leverage
    opt_ret = max(opt_ret, -1.0) 
    
    return {
        'entry_pst': entry_pst,
        'exit_pst': exit_utc.astimezone(TZ_PST),
        'duration': exit_utc - entry_utc,
        'opt_ret': opt_ret,
        'status': status,
        'entry_px': 1.00,
        'exit_px': 1.00 * (1 + opt_ret)
    }

# ==============================================================================
# 5. CORE ENGINE (Orchestrator)
# ==============================================================================
def run_backtest(start_date, end_date, initial_balance, profile, selection_mode='FIRST', params=None):
    log.info(f"⚡ RUNNING RTH BACKTEST: {profile}")
    
    if not config.DB_FILE.exists(): return [], [], 0.0, 0.0, {}
    if not params: params = {}
    
    trades = []
    balance = float(initial_balance)
    equity_curve = [{'Date': start_date, 'Balance': balance}]
    
    total_friction = 0.0
    gross_pnl_sum = 0.0
    wins = 0
    losses = 0
    
    tax_rate = float(params.get('tax_rate', 26)) / 100.0
    fee_model = params.get('fee_model', 'RH_GOLD')
    
    try:
        # --- PATH A: REALITY (Read Only) ---
        if profile in ['LIVE_RH', 'MANUAL_SIM']:
            raw_df = pd.DataFrame()
            if profile == 'LIVE_RH': raw_df = forensics.fetch_rh_data()
            else: raw_df = forensics.fetch_manual_sim_data()
            
            if not raw_df.empty:
                col = 'entry_time_utc' if 'entry_time_utc' in raw_df.columns else 'entry_time'
                raw_df['ts'] = pd.to_datetime(raw_df[col])
                if raw_df['ts'].dt.tz is None: raw_df['ts'] = raw_df['ts'].dt.tz_localize(TZ_UTC)
                else: raw_df['ts'] = raw_df['ts'].dt.tz_convert(TZ_UTC)
                raw_df['ts_pst'] = raw_df['ts'].dt.tz_convert(TZ_PST)
                
                mask = (raw_df['ts_pst'].dt.date >= pd.to_datetime(start_date).date()) & \
                       (raw_df['ts_pst'].dt.date <= pd.to_datetime(end_date).date())
                df = raw_df.loc[mask].copy().sort_values('ts')
                
                for _, row in df.iterrows():
                    pnl = row['pnl']
                    friction = 0.0
                    if profile == 'MANUAL_SIM':
                        friction = calculate_friction(1, 0, fee_model)
                        pnl -= friction
                    
                    balance += pnl
                    gross_pnl_sum += (pnl + friction)
                    total_friction += friction
                    if pnl > 0: wins += 1
                    else: losses += 1
                    
                    entry_dt = row['ts_pst']
                    if 'exit_time' in row and pd.notnull(row['exit_time']):
                        exit_raw = pd.to_datetime(row['exit_time'])
                        if exit_raw.tz is None: exit_raw = exit_raw.tz_localize(TZ_UTC)
                        exit_dt = exit_raw.tz_convert(TZ_PST)
                    else: exit_dt = entry_dt
                        
                    duration = exit_dt - entry_dt
                    dur_str = f"{int(duration.total_seconds() // 60)}m"
                    tax = pnl * tax_rate if pnl > 0 else 0.0
                    
                    trades.append({
                        'Date': entry_dt.strftime('%Y-%m-%d'),
                        'Ticker': row['ticker'],
                        'Type': row['type'],
                        'Entry_Time': entry_dt.strftime('%H:%M:%S'),
                        'Exit_Time': exit_dt.strftime('%H:%M:%S'),
                        'Duration': dur_str,
                        'PnL': pnl,
                        'Return': row.get('return_pct', 0),
                        'Balance': balance,
                        'Tax': tax,
                        'TakeHome': pnl - tax,
                        'Raw_PnL': pnl
                    })
                    equity_curve.append({'Date': entry_dt.strftime('%Y-%m-%d %H:%M'), 'Balance': balance})

        # --- PATH B: ALGO HISTORICAL (Save to DB) ---
        else:
            con = duckdb.connect(str(config.DB_FILE), read_only=True)
            q = f"SELECT * FROM {config.TBL_MANIFEST} WHERE date >= '{start_date}' AND date <= '{end_date}' ORDER BY entry_timestamp_utc ASC"
            df_sigs = con.execute(q).df()
            
            if profile == 'ALL_CALL': df_sigs = df_sigs[df_sigs['trade_type'] == 'call']
            elif profile == 'ALL_PUT': df_sigs = df_sigs[df_sigs['trade_type'] == 'put']
            
            unique_dates = df_sigs['date'].unique()
            
            for d in unique_dates:
                day_sigs = df_sigs[df_sigs['date'] == d]
                candidates = []
                
                for _, row in day_sigs.iterrows():
                    result = get_trade_outcome(con, row, params)
                    if result:
                        alloc = 500.0
                        gross = alloc * result['opt_ret']
                        fric = calculate_friction(5, 1.00, fee_model)
                        net = gross - fric
                        
                        candidates.append({
                            'time': result['entry_pst'],
                            'exit': result['exit_pst'],
                            'dur': result['duration'],
                            'ticker': f"XSP {row['trade_type'].upper()}",
                            'type': row['trade_type'].upper(),
                            'pnl': net,
                            'gross': gross,
                            'fric': fric,
                            'ret': (net/alloc)*100,
                            'status': result['status'],
                            'entry_px': result['entry_px'],
                            'exit_px': result['exit_px']
                        })
                
                if not candidates: continue
                
                selected = []
                if selection_mode == 'FIRST':
                    candidates.sort(key=lambda x: x['time'])
                    selected = [candidates[0]]
                elif selection_mode == 'ALL':
                    candidates.sort(key=lambda x: x['time'])
                    selected = candidates
                elif selection_mode == 'BEST':
                    candidates.sort(key=lambda x: x['pnl'], reverse=True)
                    selected = [candidates[0]]
                
                for t in selected:
                    balance += t['pnl']
                    gross_pnl_sum += t['gross']
                    total_friction += t['fric']
                    if t['pnl'] > 0: wins += 1
                    else: losses += 1
                    
                    dur_str = f"{int(t['dur'].total_seconds() // 60)}m"
                    tax = t['pnl'] * tax_rate if t['pnl'] > 0 else 0.0
                    
                    trades.append({
                        'Date': t['time'].strftime('%Y-%m-%d'),
                        'Ticker': t['ticker'],
                        'Type': t['type'],
                        'Entry_Time': t['time'].strftime('%H:%M:%S'),
                        'Exit_Time': t['exit'].strftime('%H:%M:%S'),
                        'Duration': dur_str,
                        'PnL': t['pnl'],
                        'Return': t['ret'],
                        'Balance': balance,
                        'Tax': tax,
                        'TakeHome': t['pnl'] - tax,
                        'Raw_Entry': t['entry_px'],
                        'Raw_Exit': t['exit_px'],
                        'Raw_PnL': t['pnl'],
                        'Raw_Ret': t['ret'],
                        'Duration_Obj': t['dur']
                    })
                    equity_curve.append({'Date': t['time'].strftime('%Y-%m-%d %H:%M'), 'Balance': balance})
            
            con.close()
            
            # --- SAVE TO DB ---
            save_simulation_to_db(trades)

    except Exception as e:
        log.error(f"Backtest Error: {e}")
        return [], [], initial_balance, 0, {}

    # Final Stats
    final_balance = balance
    total_return = ((final_balance - initial_balance) / initial_balance) * 100 if initial_balance > 0 else 0
    count = wins + losses
    win_rate = (wins / count * 100) if count > 0 else 0
    
    report = {
        'gross_pnl': gross_pnl_sum,
        'net_pnl': final_balance - initial_balance,
        'friction': total_friction,
        'count': count,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate
    }
    
    return trades, equity_curve, final_balance, total_return, report