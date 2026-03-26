# FILE: src/core/engine_backtest.py
# INSTITUTIONAL STANDARD v4.2.2 | BACKTEST & SIMULATION ENGINE (TZ-PATCHED)

import sys
import duckdb
import pandas as pd
import numpy as np
import pandas_ta as ta
import time
import shutil
import tempfile
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. PATH & ARCHITECTURE CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")
TZ_UTC = pytz.UTC

TBL_OPTIONS = getattr(config, 'TBL_OPTIONS', 'options_1m')

try:
    from src.core import engine_ml_precision
    ML_AVAILABLE = True
except ImportError:
    log.warning("ML Oracle not found. Proceeding without ML triage.")
    ML_AVAILABLE = False

# ==============================================================================
# 2. FINANCIAL CALCULATORS
# ==============================================================================
def calculate_fees(price, quantity, model='RH_GOLD'):
    if model == 'NONE': return 0.0
    reg_fee = 0.04
    taf_fee = 0.002
    contract_fee = 0.35 if model == 'RH_GOLD' else 0.65 if model == 'STD' else 1.00
    return round((contract_fee * quantity) + reg_fee + taf_fee, 2)

def calculate_taxes(profit, rate_pct):
    if profit <= 0: return 0.0
    return profit * (rate_pct / 100.0)

# ==============================================================================
# 3. SNAPSHOT PROTOCOL (Bypass Windows Write Locks)
# ==============================================================================
def get_safe_connection():
    """
    Creates a temporary clone of the DB to avoid locking the pipeline.
    CRITICAL for UI-triggered backtests.
    """
    if not config.DB_FILE.exists():
        raise FileNotFoundError(f"Database not found at {config.DB_FILE}")
        
    temp_dir = tempfile.gettempdir()
    temp_db_path = Path(temp_dir) / f"temp_backtest_{int(time.time())}.duckdb"
    
    try:
        shutil.copy2(config.DB_FILE, temp_db_path)
        con = duckdb.connect(str(temp_db_path), read_only=True)
        return con, temp_db_path
    except Exception as e:
        log.error(f"Snapshot Protocol Failed: {e}")
        # Fallback to read-only direct connection (might still lock on Windows)
        return duckdb.connect(str(config.DB_FILE), read_only=True), None

def cleanup_safe_connection(con, temp_db_path):
    if con:
        con.close()
    if temp_db_path and temp_db_path.exists():
        try:
            temp_db_path.unlink()
        except: pass

# ==============================================================================
# 4. MACHINE LEARNING BATCH PROTOCOL
# ==============================================================================
def enrich_and_predict(signals_df, con):
    if not ML_AVAILABLE or signals_df.empty:
        signals_df['ml_confidence'] = 50.0
        return signals_df
        
    log.info(f"🧠 AI GATEKEEPER: Extracting live technicals for {len(signals_df)} raw signals...")
    
    min_time = signals_df['entry_timestamp_utc'].min() - timedelta(days=2)
    
    # Ensure min_time is naive for DuckDB query
    if min_time.tzinfo is not None:
        min_time = min_time.replace(tzinfo=None)
        
    df_mkt = con.execute(f"SELECT * FROM indices_1m WHERE datetime_utc >= '{min_time}'").df()
    
    # Calculate VIX Technicals
    vix = df_mkt[df_mkt['ticker'] == 'VIX'].copy()
    if not vix.empty:
        v_macd = ta.macd(vix['close'])
        vix['macd'] = v_macd['MACD_12_26_9'] if v_macd is not None else 0
        vix['signal'] = v_macd['MACDs_12_26_9'] if v_macd is not None else 0
        vix['hist'] = v_macd['MACDh_12_26_9'] if v_macd is not None else 0
        v_diff = vix['macd'] - vix['signal']
        vix['cross'] = np.where((v_diff > 0) & (v_diff.shift(1) <= 0), 1, 0)
        vix['cross'] = np.where((v_diff < 0) & (v_diff.shift(1) >= 0), -1, vix['cross'])
        vix['rsi'] = ta.rsi(vix['close'])
        
    # Calculate XSP Technicals
    xsp = df_mkt[df_mkt['ticker'] == 'XSP'].copy()
    if not xsp.empty:
        x_macd = ta.macd(xsp['close'])
        xsp['macd'] = x_macd['MACD_12_26_9'] if x_macd is not None else 0
        xsp['signal'] = x_macd['MACDs_12_26_9'] if x_macd is not None else 0
        xsp['hist'] = x_macd['MACDh_12_26_9'] if x_macd is not None else 0
        x_diff = xsp['macd'] - xsp['signal']
        xsp['cross'] = np.where((x_diff > 0) & (x_diff.shift(1) <= 0), 1, 0)
        xsp['cross'] = np.where((x_diff < 0) & (x_diff.shift(1) >= 0), -1, xsp['cross'])
        x_adx = ta.adx(xsp['high'], xsp['low'], xsp['close'])
        xsp['adx'] = x_adx['ADX_14'] if x_adx is not None else 20

    # Ensure duckdb outputs are timezone naive for consistent merging
    vix['datetime_utc'] = pd.to_datetime(vix['datetime_utc']).dt.tz_localize(None)
    xsp['datetime_utc'] = pd.to_datetime(xsp['datetime_utc']).dt.tz_localize(None)

    # Generate Predictions
    predictions = []
    for row in signals_df.itertuples():
        # Strip timezone from signal for matching
        t_time = row.entry_timestamp_utc.replace(tzinfo=None)
        
        v_ctx = vix[vix['datetime_utc'] <= t_time].tail(1) if not vix.empty else pd.DataFrame()
        x_ctx = xsp[xsp['datetime_utc'] <= t_time].tail(1) if not xsp.empty else pd.DataFrame()
        
        if v_ctx.empty or x_ctx.empty:
            predictions.append(0.0)
            continue
            
        lv = v_ctx.iloc[0]
        lx = x_ctx.iloc[0]
        
        conf = engine_ml_precision.predict_success(
            signal_type=row.trade_type, 
            vix_val=lv['rsi'], vix_hist=lv['hist'], vix_cross=lv['cross'],
            xsp_hist=lx['hist'], xsp_cross=lx['cross'], adx=lx['adx'],
            trade_hour=row.entry_timestamp_utc.hour
        )
        predictions.append(conf)
        
    signals_df['ml_confidence'] = predictions
    filtered_df = signals_df[signals_df['ml_confidence'] >= 75.0].copy()
    log.info(f"🛡️  TRIAGE COMPLETE: {len(filtered_df)} high-probability setups survive.")
    return filtered_df

# ==============================================================================
# 5. CORE SIMULATION ENGINE (v4.2 - +3 ITM Standard)
# ==============================================================================
def run_simulation_core(start_dt, end_dt, initial_balance=1000.0, mission_params=None, is_pipeline=False, profile='ALL', selection='FIRST'):
    """
    The unified physics engine for both UI What-Ifs and Pipeline Daily routines.
    """
    # ⚡ TZ-PATCH: Ensure boundary dates are firmly UTC-aware to prevent drift
    if start_dt.tzinfo is None: start_dt = start_dt.replace(tzinfo=TZ_UTC)
    if end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=TZ_UTC)

    if mission_params is None:
        mission_params = {'ideal_gain': 30, 'trail_stop': 30, 'max_loss': 30, 'fee_model': 'RH_GOLD', 'tax_rate': 26}

    tp_mult = 1.0 + (float(mission_params.get('ideal_gain', 30)) / 100.0)
    sl_mult = 1.0 - (float(mission_params.get('max_loss', 30)) / 100.0)
    trail_pct = float(mission_params.get('trail_stop', 30)) / 100.0
    fee_model = mission_params.get('fee_model', 'RH_GOLD')
    tax_rate = float(mission_params.get('tax_rate', 26))

    # 1. Acquire Safe Connection
    con, temp_db = get_safe_connection()

    try:
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        
        # UI Profile directly applied to the SQL Query
        sig_query = f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc >= {start_ms} AND entry_timestamp_utc <= {end_ms}"
        if profile == 'ALL_CALL': sig_query += " AND trade_type LIKE '%CALL%'"
        elif profile == 'ALL_PUT': sig_query += " AND trade_type LIKE '%PUT%'"
        sig_query += " ORDER BY entry_timestamp_utc ASC"
        
        signals = con.execute(sig_query).df()
        if signals.empty: return ([], [], initial_balance, 0, {}) if not is_pipeline else []
            
        # ⚡ TZ-PATCH: Explicitly force UTC awareness on signals
        signals['entry_timestamp_utc'] = pd.to_datetime(signals['entry_timestamp_utc'], unit='ms', utc=True)
        
        # Restrain the AI Gatekeeper so it doesn't nuke manual UI tests
        if is_pipeline or profile == 'ALGO_SIGNALS':
            signals = enrich_and_predict(signals, con)
        
        capital = float(initial_balance)
        trades_log = []
        equity_curve = []
        wins, losses = 0, 0
        total_gross = 0.0
        total_fees = 0.0
        
        log.info(f"⚡ Simulating {len(signals)} Trades (Target: +{mission_params.get('ideal_gain')}%, Trail: {mission_params.get('trail_stop')}%)")
        
        for row in signals.itertuples():
            entry_time = row.entry_timestamp_utc
            entry_price_xsp = float(row.xsp_price) if hasattr(row, 'xsp_price') and not pd.isna(row.xsp_price) else 0.0
            is_call = 'CALL' in row.trade_type
            op_type = 'C' if is_call else 'P'
            
            # ⚡ TZ-PATCH: Query using naive timestamp for duckdb
            entry_time_naive = entry_time.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')
            entry_time_upper = (entry_time + timedelta(minutes=5)).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')

            # Spot Price Fallback - Fetch live XSP price if signal data is missing it
            if entry_price_xsp <= 0.0:
                try:
                    spot_df = con.execute(f"SELECT close FROM indices_1m WHERE ticker = 'XSP' AND datetime_utc >= '{entry_time_naive}' ORDER BY datetime_utc ASC LIMIT 1").df()
                    if not spot_df.empty: entry_price_xsp = float(spot_df.iloc[0]['close'])
                except: pass
            if entry_price_xsp <= 0.0: continue  # Ultimate failsafe
            
            # 🩹 RESILIENT FIX: Find the correct strike FIRST, independent of the exact minute
            strike_q = f"""
                SELECT DISTINCT ticker 
                FROM {TBL_OPTIONS}
                WHERE datetime_utc >= '{entry_time_naive}' AND datetime_utc <= '{entry_time_upper}'
                AND SUBSTRING(ticker, 10, 1) = '{op_type}'
            """
            
            # Select +3 ITM Strike (Calls count DOWN from spot, Puts count UP from spot)
            if is_call: 
                strike_q += f" AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT) / 1000.0 < {entry_price_xsp} ORDER BY ticker DESC LIMIT 1 OFFSET 2"
            else: 
                strike_q += f" AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT) / 1000.0 > {entry_price_xsp} ORDER BY ticker ASC LIMIT 1 OFFSET 2"
                
            try: strike_df = con.execute(strike_q).df()
            except: continue
            
            if strike_df.empty: continue
            c_ticker = strike_df.iloc[0]['ticker']
            
            # Now, find the FIRST available premium for that specific contract within the 5-minute window
            premium_q = f"""
                SELECT close as entry_premium, datetime_utc as exact_time 
                FROM {TBL_OPTIONS} 
                WHERE ticker = '{c_ticker}' 
                AND datetime_utc >= '{entry_time_naive}' AND datetime_utc <= '{entry_time_upper}' 
                ORDER BY datetime_utc ASC LIMIT 1
            """
            try: contract_df = con.execute(premium_q).df()
            except: continue
            
            if contract_df.empty: continue
            
            entry_premium = float(contract_df.iloc[0]['entry_premium'])
            if entry_premium <= 0.05: continue
            
            # Lock in the actual execution time for the tracking trajectory
            exact_time_match = contract_df.iloc[0]['exact_time'].strftime('%Y-%m-%d %H:%M:%S')
                
            qty = max(1, int(capital // (entry_premium * 100))) 
            
            # Execution Targets
            target_premium = entry_premium * tp_mult 
            hard_stop_premium = entry_premium * sl_mult 
            
            # Look ahead 4 hours for exit resolution
            exit_boundary_naive = (entry_time + timedelta(hours=4)).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')
            track_q = f"SELECT datetime_utc, high, low, close FROM {TBL_OPTIONS} WHERE ticker = '{c_ticker}' AND datetime_utc > '{exact_time_match}' AND datetime_utc <= '{exit_boundary_naive}' ORDER BY datetime_utc ASC"
            try: trajectory = con.execute(track_q).df()
            except: continue
            if trajectory.empty: continue
                
            status = 'LOSS'; reason = 'TIME_EXHAUSTION'
            exit_premium = trajectory.iloc[-1]['close']; exit_time = pd.to_datetime(trajectory.iloc[-1]['datetime_utc'], utc=True)
            
            highest_px = entry_premium
            dynamic_stop = hard_stop_premium

            # The Engine Physics (Tick by Tick)
            for t_row in trajectory.itertuples():
                # 1. Update High Water Mark
                if t_row.high > highest_px:
                    highest_px = t_row.high
                    # Trailing Stop calculation
                    trail_level = highest_px * (1.0 - trail_pct)
                    if trail_level > dynamic_stop:
                        dynamic_stop = trail_level
                
                # 2. Check Stop Loss (Hard or Trailing)
                if t_row.low <= dynamic_stop:
                    status = 'WIN' if dynamic_stop > entry_premium else 'LOSS'
                    exit_premium = dynamic_stop
                    reason = 'TRAILING_STOP' if dynamic_stop > entry_premium else 'HARD_STOP'
                    if status == 'WIN': wins += 1
                    else: losses += 1
                    exit_time = pd.to_datetime(t_row.datetime_utc, utc=True)
                    break
                    
                # 3. Check Ideal Target (Take Profit)
                if t_row.high >= target_premium:
                    status = 'WIN'; exit_premium = target_premium; reason = 'IDEAL_TARGET'; wins += 1
                    exit_time = pd.to_datetime(t_row.datetime_utc, utc=True)
                    break
            
            if reason == 'TIME_EXHAUSTION':
                if exit_premium > entry_premium: wins += 1; status = 'WIN'
                else: losses += 1
                
            # Accounting
            gross_pnl = (exit_premium - entry_premium) * 100 * qty
            fees = calculate_fees(entry_premium, qty, fee_model)
            net_pnl = gross_pnl - fees
            
            tax = calculate_taxes(net_pnl, tax_rate)
            take_home = net_pnl - tax
            
            capital += take_home
            total_gross += gross_pnl
            total_fees += fees
            
            # ⚡ TZ-PATCH: Safe duration math
            duration_mins = int((exit_time - entry_time).total_seconds() / 60)
            
            # Log format tailored for UI Display
            local_entry = entry_time.tz_convert(config.TZ_LOCAL).strftime('%m-%d %H:%M')
            local_exit = exit_time.tz_convert(config.TZ_LOCAL).strftime('%m-%d %H:%M')

            trades_log.append({
                'Date': entry_time.strftime('%Y-%m-%d'),
                'Entry_Time': local_entry,
                'Exit_Time': local_exit,
                'Ticker': c_ticker,
                'Type': row.trade_type,
                'Duration': f"{duration_mins}m",
                'Return': ((exit_premium - entry_premium) / entry_premium) * 100,
                'Tax': tax,
                'TakeHome': take_home,
                'Balance': capital,
                # Fields below are required for the pipeline DB insert
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M:%S'),
                'entry_price': entry_premium,
                'exit_price': exit_premium,
                'quantity': qty,
                'net_pnl': net_pnl,
                'reason': reason,
                'status': status,
                'action': 'BUY',
                'source_id': 'BACKTEST',
                'return_pct': ((exit_premium - entry_premium) / entry_premium) * 100,
                'ticker_raw': c_ticker
            })
            
            equity_curve.append({'Date': local_entry, 'Balance': capital})

    finally:
        cleanup_safe_connection(con, temp_db)

    # 4. Pipeline vs UI Return Router
    if is_pipeline:
        return trades_log

    # Prepare UI Report
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    net_total = total_gross - total_fees
    net_ret_pct = ((capital - initial_balance) / initial_balance) * 100

    report = {
        'net_pnl': net_total,
        'win_rate': win_rate,
        'count': total_trades,
        'wins': wins,
        'losses': losses,
        'gross_pnl': total_gross,
        'friction': total_fees
    }

    return trades_log, equity_curve, capital, net_ret_pct, report

# ==============================================================================
# 6. DUAL ENGINE EXPORTS
# ==============================================================================

def run_backtest(start_date, end_date, initial_balance, profile, selection, mission_params):
    """
    ENGINE 1: Called by view_data_generator.py (The Glass).
    Returns complex tuples (trades, equity_curve, final_bal, ret_pct, report).
    """
    s_dt = datetime.strptime(str(start_date).split('T')[0], "%Y-%m-%d").replace(tzinfo=pytz.UTC)
    e_dt = datetime.strptime(str(end_date).split('T')[0], "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=pytz.UTC)
    
    return run_simulation_core(s_dt, e_dt, initial_balance, mission_params, is_pipeline=False, profile=profile, selection=selection)

def run_backtest_session(initial_balance=1000.0, days=59):
    """
    ENGINE 2: Called by main_pipeline.py (The Daemon).
    Returns a simple list of trades for database ingestion.
    """
    log.info(f"🧪 AUTO-BACKTEST PROTOCOL: Last {days} days. Starting Balance: ${initial_balance}")
    end_dt = datetime.now(pytz.UTC)
    start_dt = end_dt - timedelta(days=days)
    
    mission_params = {'ideal_gain': 30, 'trail_stop': 30, 'max_loss': 30, 'fee_model': 'RH_GOLD', 'tax_rate': 26}
    
    trades = run_simulation_core(start_dt, end_dt, initial_balance, mission_params, is_pipeline=True)
    
    # Save to DB for Pipeline
    if trades:
        try:
            df_write = pd.DataFrame(trades)
            # Select only the DB-required columns
            db_cols = ['entry_time', 'exit_time', 'ticker_raw', 'entry_price', 'exit_price', 'quantity', 'net_pnl', 'return_pct', 'reason', 'status', 'action', 'source_id']
            df_write = df_write.rename(columns={'ticker_raw': 'ticker'})[db_cols]
            
            con_write = duckdb.connect(str(config.DB_FILE))
            con_write.execute(f"DELETE FROM {config.TBL_SIM_LOG} WHERE source_id = 'BACKTEST'")
            con_write.register('df_write_temp', df_write)
            cols_str = ", ".join(df_write.columns)
            con_write.execute(f"INSERT INTO {config.TBL_SIM_LOG} ({cols_str}) SELECT * FROM df_write_temp")
            con_write.close()
            log.info(f"💾 Backtest Commit successful: {len(df_write)} trades saved.")
        except Exception as e:
            log.error(f"❌ DB Write Error during commit: {e}")

    return trades

if __name__ == "__main__":
    run_backtest_session(days=30)