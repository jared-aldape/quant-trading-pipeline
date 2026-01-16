import sys
import duckdb
import pandas as pd
import shutil
import os
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

# ==============================================================================
# 2. CALCULATORS
# ==============================================================================
def calculate_fees(price, quantity, model='RH_GOLD'):
    if model == 'NONE': return 0.0
    reg_fee = 0.04
    taf_fee = 0.002
    contract_fee = 0.35 if model == 'RH_GOLD' else 0.65 if model == 'STD' else 1.00 if model == 'PROP' else 0.0
    return round((contract_fee * quantity) + reg_fee + taf_fee, 2)

def calculate_tax(gross_profit, rate_pct=26):
    return gross_profit * (float(rate_pct) / 100.0) if gross_profit > 0 else 0.0

# ==============================================================================
# 3. ROBUST SNAPSHOT (BINARY BYPASS)
# ==============================================================================
def get_safe_connection():
    """Attempts to clone the DB using binary stream to bypass Windows locks."""
    db_path = config.DB_FILE
    temp_path = db_path.parent / "temp_view_engine.duckdb"
    
    # 1. Try Standard Copy
    try:
        shutil.copy2(db_path, temp_path)
    except OSError:
        # 2. Fallback: Binary Read (Often works on open files)
        try:
            with open(db_path, 'rb') as src, open(temp_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        except Exception as e:
            log.warning(f"⚠️ DATABASE LOCKED (DailyHarvest Active?): {e}")
            return None, None

    # 3. Connect to Clone
    try:
        con = duckdb.connect(str(temp_path), read_only=True)
        return con, temp_path
    except Exception as e:
        log.error(f"Clone Connection Failed: {e}")
        return None, None

def cleanup_temp_db(con, temp_path):
    try:
        if con: con.close()
        if temp_path and temp_path.exists(): os.remove(temp_path)
    except: pass

# ==============================================================================
# 4. ANALYSIS LOGIC
# ==============================================================================
def quick_outcome_lookup(con, entry_ts, trade_type, strike_est):
    try:
        entry_dt = datetime.fromtimestamp(entry_ts/1000)
        start_str = entry_dt.strftime('%Y-%m-%d %H:%M:%S')
        end_str = (entry_dt + timedelta(minutes=45)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Using Index Data for Speed
        q = f"SELECT open, close FROM {config.TBL_INDICES} WHERE ticker IN ('SPX', 'XSP') AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
        df_price = con.execute(q).df()
        
        if df_price.empty: return None, 0.0, 0
        
        entry_px = df_price.iloc[0]['open']
        exit_px = df_price.iloc[-1]['close']
        delta_pct = (exit_px - entry_px) / entry_px
        
        t_type = str(trade_type).lower()
        # Simulated 10x Leverage for Options
        roi = (delta_pct * 10.0) if 'call' in t_type else (-delta_pct * 10.0)
            
        return 100.0 * roi, exit_px, 45
    except: return None, 0.0, 0

# ==============================================================================
# 5. MAIN ENGINE
# ==============================================================================
def run_backtest(start_date, end_date, start_capital, profile, selection_mode, mission_params):
    log.info(f"🧪 BACKTEST REQUEST: {start_date} to {end_date}")
    
    capital = float(start_capital) if start_capital is not None else 1000.0
    equity_curve = [{'Date': start_date, 'Balance': capital}]
    trades_log = []
    report = {'net_pnl': 0.0, 'gross_pnl': 0.0, 'friction': 0.0, 'win_rate': 0.0, 'count': 0, 'wins': 0, 'losses': 0}
    
    if not config.DB_FILE.exists(): return [], equity_curve, capital, 0.0, report

    # ⚡ USE SNAPSHOT PROTOCOL
    con, temp_path = get_safe_connection()
    if not con:
        # If lock persists, return empty results (prevents crash)
        log.warning("Skipping Backtest: Database is strictly locked.")
        return [], equity_curve, capital, 0.0, report

    try:
        query = f"SELECT * FROM {config.TBL_MANIFEST} WHERE date >= '{start_date}' AND date <= '{end_date}' ORDER BY entry_timestamp_utc ASC"
        signals = con.execute(query).df()
        
        if not signals.empty and 'trade_type' in signals.columns:
            signals['type_norm'] = signals['trade_type'].astype(str).str.lower().str.strip()
            if profile == 'ALL_CALL': signals = signals[signals['type_norm'] == 'call']
            elif profile == 'ALL_PUT': signals = signals[signals['type_norm'] == 'put']

        next_available_entry = 0 
        gross_pnl, total_fees, wins, losses = 0.0, 0.0, 0, 0

        for _, row in signals.iterrows():
            entry_ts = row['entry_timestamp_utc']
            if entry_ts < next_available_entry: continue

            pnl_raw, _, duration = quick_outcome_lookup(con, entry_ts, row['trade_type'], row['xsp_price'])
            if pnl_raw is None: continue
            
            next_available_entry = entry_ts + (duration * 60 * 1000)
            risk_amt = capital * 0.05 
            roi_pct = pnl_raw / 100.0 
            
            p_gain = float(mission_params.get('ideal_gain', 100)) / 100.0
            p_loss = -float(mission_params.get('max_loss', 50)) / 100.0
            if roi_pct > p_gain: roi_pct = p_gain
            if roi_pct < p_loss: roi_pct = p_loss
            
            gross_trade_pnl = risk_amt * roi_pct
            fees = calculate_fees(1.0, 1, model=mission_params.get('fee_model', 'RH_GOLD'))
            tax = calculate_tax(gross_trade_pnl, rate_pct=float(mission_params.get('tax_rate', 26)))
            
            net_trade_pnl = gross_trade_pnl - fees - tax
            capital += net_trade_pnl
            gross_pnl += gross_trade_pnl
            total_fees += fees
            if net_trade_pnl > 0: wins += 1
            else: losses += 1
            
            entry_dt = datetime.fromtimestamp(entry_ts/1000)
            trades_log.append({
                'Date': entry_dt.strftime('%Y-%m-%d'),
                'Ticker': f"SIM-{str(row['trade_type']).upper()}",
                'Type': str(row['trade_type']).upper(),
                'Entry_Time': entry_dt.strftime('%H:%M'),
                'Exit_Time': (entry_dt + timedelta(minutes=duration)).strftime('%H:%M'),
                'Duration': f"{duration}m",
                'Raw_Entry': 1.0, 'Raw_Exit': 1.0 + roi_pct,
                'PnL': net_trade_pnl, 'Return': roi_pct * 100,
                'Balance': capital, 'Tax': tax, 'TakeHome': net_trade_pnl 
            })
            equity_curve.append({'Date': entry_dt.strftime('%Y-%m-%d %H:%M'), 'Balance': capital})

    except Exception as e:
        log.error(f"Backtest Logic Error: {e}")
    finally:
        cleanup_temp_db(con, temp_path)
    
    total_trades = wins + losses
    net_pnl = capital - float(start_capital if start_capital is not None else 1000.0)
    ret_pct = (net_pnl / float(start_capital if start_capital is not None else 1000.0)) * 100
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    report = {'net_pnl': net_pnl, 'gross_pnl': gross_pnl, 'friction': total_fees, 'win_rate': win_rate, 'count': total_trades, 'wins': wins, 'losses': losses}
    
    return trades_log, equity_curve, capital, ret_pct, report

# Stub for pipeline compatibility
def run_backtest_session(initial_balance=1000.0, days=1, selection_mode='FIRST', hedged_mode=True):
    defaults = {'ideal_gain': 100, 'max_loss': 50, 'fee_model': 'RH_GOLD', 'tax_rate': 0}
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')
    trades, _, _, _, _ = run_backtest(start, end, initial_balance, 'ALGO_SIGNALS', selection_mode, defaults)
    return pd.DataFrame(trades)

if __name__ == "__main__":
    run_backtest_session()