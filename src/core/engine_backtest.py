import sys
import duckdb
import pandas as pd
import numpy as np
import shutil
import os
import time
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")
TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')
TZ_NY = pytz.timezone('America/New_York')

try:
    from src.core import engine_ml_precision
    ML_AVAILABLE = True
except ImportError:
    log.warning("ML Oracle not found. 'BEST' selection mode will default to 'FIRST'.")
    ML_AVAILABLE = False

# ==============================================================================
# 2. CALCULATORS
# ==============================================================================
def calculate_fees(price, quantity, model='RH_GOLD'):
    if model == 'NONE': return 0.0
    reg_fee = 0.04
    taf_fee = 0.002
    contract_fee = 0.35 if model == 'RH_GOLD' else 0.65 if model == 'STD' else 1.00 if model == 'PROP' else 0.0
    return round((contract_fee * quantity) + reg_fee + taf_fee, 2)

# ==============================================================================
# 3. SNAPSHOT PROTOCOL
# ==============================================================================
def get_safe_connection():
    db_path = config.DB_FILE
    temp_path = db_path.parent / "temp_view_engine.duckdb"
    
    try: shutil.copy2(db_path, temp_path)
    except OSError:
        try:
            with open(db_path, 'rb') as src, open(temp_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        except Exception as e:
            return None, None

    try:
        con = duckdb.connect(str(temp_path), read_only=True)
        return con, temp_path
    except Exception as e:
        return None, None

def cleanup_temp_db(con, temp_path):
    try:
        if con: con.close()
        if temp_path and temp_path.exists(): os.remove(temp_path)
    except: pass

# ==============================================================================
# 4. ANALYSIS LOGIC
# ==============================================================================
def quick_outcome_lookup(con, entry_ts, trade_type, strike_est, mission_params):
    try:
        entry_dt_utc = datetime.fromtimestamp(entry_ts/1000, tz=TZ_UTC)
        entry_dt_ny = entry_dt_utc.astimezone(TZ_NY)
        
        eod_ny = entry_dt_ny.replace(hour=16, minute=0, second=0, microsecond=0)
        eod_utc = eod_ny.astimezone(TZ_UTC)
        
        start_str = entry_dt_utc.strftime('%Y-%m-%d %H:%M:%S')
        end_str = eod_utc.strftime('%Y-%m-%d %H:%M:%S')
        
        q = f"SELECT datetime_utc, close FROM {config.TBL_INDICES} WHERE ticker IN ('SPX', 'XSP') AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
        df_price = con.execute(q).df()
        
        if df_price.empty: return None, 0.0, 0.0, 0, ""
        
        entry_px = df_price.iloc[0]['close']
        t_type = str(trade_type).lower()
        is_call = 'call' in t_type
        
        df_price['delta_pct'] = (df_price['close'] - entry_px) / entry_px
        if is_call: df_price['roi_pct'] = df_price['delta_pct'] * 50.0 * 100.0 
        else: df_price['roi_pct'] = -df_price['delta_pct'] * 50.0 * 100.0

        exit_idx = df_price['roi_pct'].idxmax()
        exit_row = df_price.loc[exit_idx]

        exit_roi = exit_row['roi_pct']
        exit_px_val = exit_row['close']
        
        exit_dt_utc = pd.to_datetime(exit_row['datetime_utc'])
        if exit_dt_utc.tz is None: exit_dt_utc = exit_dt_utc.tz_localize('UTC')
        duration = max(1, int((exit_dt_utc - entry_dt_utc).total_seconds() / 60))

        base_price = float(strike_est) if (strike_est is not None and not pd.isna(strike_est)) else float(entry_px)
        target_strike = int(round(base_price))
        strike_fmt = f"{target_strike * 1000:08d}"
        
        date_fmt = entry_dt_ny.strftime('%y%m%d')
        opt_code = 'C' if is_call else 'P'
        actual_ticker = f"XSP{date_fmt}{opt_code}{strike_fmt}"
            
        return exit_roi, entry_px, exit_px_val, duration, actual_ticker
    except Exception as e: 
        return None, 0.0, 0.0, 0, ""

# ==============================================================================
# 5. MAIN ENGINE
# ==============================================================================
def run_backtest(start_date, end_date, start_capital, profile, selection_mode, mission_params):
    log.info(f"🧪 BACKTEST REQUEST: {start_date} to {end_date}")
    
    capital = float(start_capital) if start_capital is not None else 150.0
    
    equity_curve = [{'Date': start_date, 'Balance': capital}]
    trades_log = []
    db_records = [] 
    report = {'net_pnl': 0.0, 'gross_pnl': 0.0, 'friction': 0.0, 'win_rate': 0.0, 'count': 0, 'wins': 0, 'losses': 0}
    
    if not config.DB_FILE.exists(): return [], equity_curve, capital, 0.0, report

    con, temp_path = get_safe_connection()
    if not con: return [], equity_curve, capital, 0.0, report

    try:
        query = f"SELECT * FROM {config.TBL_MANIFEST} WHERE date >= '{start_date}' AND date <= '{end_date}' ORDER BY entry_timestamp_utc ASC"
        signals = con.execute(query).df()
        
        if not signals.empty and 'trade_type' in signals.columns:
            signals['type_norm'] = signals['trade_type'].astype(str).str.lower().str.strip()
            if profile == 'ALL_CALL': signals = signals[signals['type_norm'] == 'call']
            elif profile == 'ALL_PUT': signals = signals[signals['type_norm'] == 'put']

        gross_pnl, total_fees, wins, losses = 0.0, 0.0, 0, 0
        last_traded_date = None
        
        high_water_mark = capital
        tax_rate_pct = float(mission_params.get('tax_rate', 26)) / 100.0

        for _, row in signals.iterrows():
            current_date_str = str(row['date'])
            if current_date_str == last_traded_date: continue
                
            entry_ts = row['entry_timestamp_utc']

            if selection_mode == 'BEST' and ML_AVAILABLE:
                vix_val = row['vix_value'] if 'vix_value' in row else 15.0
                rsi_val = row['rsi_value'] if 'rsi_value' in row else 50.0
                entry_dt_utc = datetime.fromtimestamp(entry_ts/1000, tz=TZ_UTC)
                trade_hour = entry_dt_utc.astimezone(TZ_PST).hour
                
                try: win_prob = engine_ml_precision.predict_success(row['trade_type'], vix_val, rsi_val, trade_hour=trade_hour)
                except TypeError: win_prob = engine_ml_precision.predict_success(row['trade_type'], vix_val, rsi_val)

                if win_prob < 51.0: continue

            pnl_raw, entry_px, exit_px_val, duration, actual_ticker = quick_outcome_lookup(con, entry_ts, row['trade_type'], row['xsp_price'], mission_params)
            if pnl_raw is None: continue
            
            risk_pct = 1.0 
            max_risk_amt = capital * risk_pct 
            
            est_premium = 1.50 
            contract_cost = est_premium * 100.0
            
            qty = max(1, int(max_risk_amt // contract_cost)) if max_risk_amt >= contract_cost else 0
            if qty == 0: continue 
            
            actual_deployed = qty * contract_cost
            roi_pct = pnl_raw / 100.0 
            
            gross_trade_pnl = actual_deployed * roi_pct
            fees = calculate_fees(est_premium, qty, model=mission_params.get('fee_model', 'RH_GOLD'))
            
            net_trade_before_tax = gross_trade_pnl - fees
            proposed_capital = capital + net_trade_before_tax
            
            tax = 0.0
            if proposed_capital > high_water_mark and tax_rate_pct > 0:
                taxable_amount = proposed_capital - high_water_mark
                tax = taxable_amount * tax_rate_pct
                high_water_mark = proposed_capital 
            
            net_trade_pnl = net_trade_before_tax - tax
            capital += net_trade_pnl
            gross_pnl += gross_trade_pnl
            total_fees += fees
            if net_trade_pnl > 0: wins += 1
            else: losses += 1
            
            last_traded_date = current_date_str
            
            entry_dt_utc = datetime.fromtimestamp(entry_ts/1000, tz=TZ_UTC)
            exit_dt_utc = entry_dt_utc + timedelta(minutes=duration)
            entry_dt_pst = entry_dt_utc.astimezone(TZ_PST)
            
            trades_log.append({
                'Date': entry_dt_pst.strftime('%Y-%m-%d'),
                'Ticker': actual_ticker,
                'Type': str(row['trade_type']).upper(),
                'Entry_Time': entry_dt_pst.strftime('%H:%M'),
                'Exit_Time': (entry_dt_pst + timedelta(minutes=duration)).strftime('%H:%M'),
                'Duration': f"{duration}m",
                'Raw_Entry': actual_deployed, 'Raw_Exit': actual_deployed + gross_trade_pnl,
                'PnL': net_trade_pnl, 'Return': roi_pct * 100,
                'Balance': capital, 'Tax': tax, 'TakeHome': net_trade_pnl 
            })
            equity_curve.append({'Date': entry_dt_pst.strftime('%Y-%m-%d %H:%M'), 'Balance': capital})

            db_records.append({
                'entry_time': entry_dt_utc.replace(tzinfo=None), 
                'exit_time': exit_dt_utc.replace(tzinfo=None),
                'ticker': actual_ticker,
                'net_pnl': net_trade_pnl,
                'return_pct': roi_pct * 100.0,
                'reason': 'MFE_PEAK',
                'entry_price': float(entry_px),
                'exit_price': float(exit_px_val),
                'action': 'BUY',
                'quantity': float(qty),
                'source_id': 'BACKTEST',
                'status': 'CLOSED'
            })

    except Exception as e:
        log.error(f"Backtest Logic Error: {e}")
    finally:
        cleanup_temp_db(con, temp_path)
    
    # ⚡ THE AUTO-HEAL PROTOCOL
    if db_records:
        df_write = pd.DataFrame(db_records)
        cols_str = ", ".join(df_write.columns)
        
        for attempt in range(5):
            try:
                con_write = duckdb.connect(str(config.DB_FILE))
                
                # Force Database to accept our updated Schema variables
                try:
                    existing_cols = [c[0] for c in con_write.execute(f"DESCRIBE {config.TBL_SIM_LOG}").fetchall()]
                    for col in df_write.columns:
                        if col not in existing_cols:
                            ctype = "DOUBLE" if df_write[col].dtype == 'float64' else "VARCHAR"
                            if df_write[col].dtype.name.startswith('datetime'): ctype = "TIMESTAMP"
                            con_write.execute(f"ALTER TABLE {config.TBL_SIM_LOG} ADD COLUMN {col} {ctype}")
                except Exception:
                    pass

                try: con_write.execute(f"DELETE FROM {config.TBL_SIM_LOG} WHERE source_id = 'BACKTEST'")
                except: pass
                
                con_write.register('df_write_temp', df_write)
                con_write.execute(f"INSERT INTO {config.TBL_SIM_LOG} ({cols_str}) SELECT * FROM df_write_temp")
                con_write.close()
                log.info(f"💾 Auto-Heal & Commit successful: {len(df_write)} trades saved.")
                break
            except Exception as write_err:
                log.warning(f"DB Lock collision, retrying... {write_err}")
                time.sleep(1)

    start_cap_float = float(start_capital) if start_capital is not None else 150.0
    total_trades = wins + losses
    net_pnl = capital - start_cap_float
    ret_pct = (net_pnl / start_cap_float) * 100 if start_cap_float > 0 else 0.0
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    report = {'net_pnl': net_pnl, 'gross_pnl': gross_pnl, 'friction': total_fees, 'win_rate': win_rate, 'count': total_trades, 'wins': wins, 'losses': losses}
    
    return trades_log, equity_curve, capital, ret_pct, report