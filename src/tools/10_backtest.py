import sys
import os
import argparse
import duckdb
import pandas as pd
import numpy as np
import json
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")

# ==============================================================================
# 2. ARGUMENT PARSING
# ==============================================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Quant OS v2.2 Backtester (Real Data)")
    parser.add_argument("--start_date", type=str, required=True)
    parser.add_argument("--end_date", type=str, required=True)
    parser.add_argument("--start_balance", type=float, required=True)
    parser.add_argument("--pos_size_pct", type=float, required=True)
    parser.add_argument("--max_invest", type=float, required=True)
    parser.add_argument("--tax_rate", type=float, default=0.268)
    parser.add_argument("--trailing_stop_pct", type=float, default=0.25)
    parser.add_argument("--ideal_gain_pct", type=float, default=0.0) 
    parser.add_argument("--enforce_rth", type=str, default="False") 
    parser.add_argument("--archive_report", type=str, default="True")
    parser.add_argument("--selection_mode", type=str, default="FIRST", choices=["FIRST", "BEST"])
    parser.add_argument("--strike_offset", type=int, default=0)
    parser.add_argument("--skip_open_minutes", type=int, default=15)
    return parser.parse_args()

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def construct_ticker(date_str, xsp_price, offset=0):
    try:
        dt = pd.to_datetime(date_str)
        yymmdd = dt.strftime('%y%m%d')
        atm_strike = int(round(xsp_price))
        target_strike = atm_strike + offset
        strike_str = f"{target_strike * 1000:08d}"
        return f"O:XSP{yymmdd}C{strike_str}"
    except: return None

def simulate_real_outcome(df_opts, entry_price, trailing_stop_pct, ideal_gain_pct):
    highest_price = entry_price
    current_stop = entry_price * (1 - trailing_stop_pct)
    target_price = entry_price * (1 + ideal_gain_pct) if ideal_gain_pct > 0 else None
    
    for i, row in df_opts.iterrows():
        price_low = row['low']
        price_high = row['high']
        time_utc = row['datetime_utc']
        
        if target_price and price_high >= target_price: return target_price, time_utc, "TARGET"
        if price_low <= current_stop: return current_stop, time_utc, "STOP"
        
        if price_high > highest_price:
            highest_price = price_high
            new_stop = highest_price * (1 - trailing_stop_pct)
            if new_stop > current_stop: current_stop = new_stop
                
    last_row = df_opts.iloc[-1]
    return last_row['close'], last_row['datetime_utc'], "EOD"

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def run_backtest(args):
    log.info(f"🚀 ENGINE START | Mode: {args.selection_mode} | Offset: {args.strike_offset}")
    
    # Connect RW for the final write, RO for the fetch
    con = duckdb.connect(str(config.DB_FILE)) 
    
    # 1. FETCH SIGNALS
    query_manifest = f"SELECT * FROM {config.TBL_MANIFEST} WHERE date BETWEEN '{args.start_date}' AND '{args.end_date}' ORDER BY entry_timestamp_utc ASC"
    try:
        manifest_df = con.execute(query_manifest).df()
    except Exception as e:
        print(json.dumps({"error": "DB Error"}))
        return

    if manifest_df.empty:
        print(json.dumps({"error": "No Signals in Manifest"}))
        return

    # 2. CHECK OPTION DATA
    try: con.execute(f"SELECT 1 FROM {config.TBL_OPTIONS} LIMIT 1")
    except: 
        print(json.dumps({"error": "Option Data Missing. Run Tool 3 first."}))
        return
    
    candidate_trades = []
    
    for _, signal in manifest_df.iterrows():
        entry_time_ms = signal['entry_timestamp_utc']
        entry_dt_utc = pd.to_datetime(entry_time_ms, unit='ms', utc=True)
        entry_ny = entry_dt_utc.tz_convert(config.TZ_NY)
        market_open = entry_ny.replace(hour=9, minute=30, second=0, microsecond=0)
        
        if (entry_ny - market_open).total_seconds() / 60 < args.skip_open_minutes: continue
            
        ticker = construct_ticker(signal['date'], signal['xsp_price'], args.strike_offset)
        if not ticker: continue

        opt_query = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= to_timestamp({entry_time_ms}/1000) ORDER BY datetime_utc ASC"
        try: df_opts = con.execute(opt_query).df()
        except: continue 
        
        if df_opts.empty: continue 
            
        entry_price = df_opts.iloc[0]['close']
        entry_time = df_opts.iloc[0]['datetime_utc']
        exit_price, exit_time, reason = simulate_real_outcome(df_opts, entry_price, args.trailing_stop_pct, args.ideal_gain_pct)
        roi_pct = (exit_price - entry_price) / entry_price
        
        candidate_trades.append({
            'Entry Time': entry_time, 'Exit Time': exit_time, 'Ticker': ticker,
            'Entry Price': entry_price, 'Exit Price': exit_price,
            'Return %': roi_pct, 'Reason': reason,
            'Day': pd.to_datetime(entry_time).date()
        })

    if not candidate_trades:
        print(json.dumps({"error": "No Trades Found"}))
        con.close()
        return

    # 3. SELECT TRADES
    candidates_df = pd.DataFrame(candidate_trades)
    final_trades = []
    for day, group in candidates_df.groupby('Day'):
        if args.selection_mode == "BEST":
            selected = group.sort_values('Return %', ascending=False).iloc[0]
            selected['Reason'] += " (Best)"
        else:
            selected = group.sort_values('Entry Time').iloc[0]
        final_trades.append(selected)
        
    final_trades_df = pd.DataFrame(final_trades).sort_values('Entry Time')

    # 4. CALCULATE EQUITY
    balance = args.start_balance
    equity_curve = [balance]
    processed_trades = []
    
    for _, trade in final_trades_df.iterrows():
        if balance <= 0: break 
        invest_target = balance * args.pos_size_pct
        invest_amt = max(0.0, min(invest_target, args.max_invest))
        if invest_amt == 0: continue

        pnl = invest_amt * trade['Return %']
        net_pnl = pnl - (pnl * args.tax_rate if pnl > 0 else 0)
        balance += net_pnl
        equity_curve.append(balance)
        
        processed_trades.append({
            'entry_time': trade['Entry Time'], # Naming for DB
            'ticker': trade['Ticker'],
            'net_pnl': net_pnl,
            'return_pct': trade['Return %'],
            'reason': trade['Reason'],
            'entry_price': trade['Entry Price'],
            'exit_price': trade['Exit Price']
        })

    # --------------------------------------------------------------------------
    # PHASE 5: DATABASE PERSISTENCE (THE UPGRADE)
    # --------------------------------------------------------------------------
    if processed_trades:
        log_df = pd.DataFrame(processed_trades)
        
        # Ensure UTC alignment for DB
        if log_df['entry_time'].dt.tz is None:
            log_df['entry_time'] = log_df['entry_time'].dt.tz_localize(config.TZ_UTC)
        else:
            log_df['entry_time'] = log_df['entry_time'].dt.tz_convert(config.TZ_UTC)
            
        log_df['entry_time'] = log_df['entry_time'].dt.tz_localize(None) # Naive UTC for DuckDB

        # Transactional Overwrite
        con.execute("CREATE TABLE IF NOT EXISTS active_simulation_log (entry_time TIMESTAMP, ticker VARCHAR, net_pnl DOUBLE, return_pct DOUBLE, reason VARCHAR, entry_price DOUBLE, exit_price DOUBLE)")
        con.execute("DELETE FROM active_simulation_log") # Wipe old run
        con.execute("INSERT INTO active_simulation_log SELECT * FROM log_df")
        log.info(f"💾 Saved {len(log_df)} trades to 'active_simulation_log' table.")

    con.close()

    # 6. REPORT
    display_df = pd.DataFrame(processed_trades)
    if not display_df.empty:
        display_df['Date'] = pd.to_datetime(display_df['entry_time'], utc=True).dt.tz_convert(config.TZ_LOCAL).dt.strftime('%Y-%m-%d %H:%M')
        win_rate = len(display_df[display_df['net_pnl'] > 0]) / len(display_df) * 100
    else:
        win_rate = 0.0
        
    equity_s = pd.Series(equity_curve)
    drawdown = (equity_s - equity_s.cummax()) / equity_s.cummax()
    max_dd_pct = drawdown.min() * 100 if not drawdown.empty else 0.0
    
    result_payload = {
        "final_balance": balance,
        "total_return_pct": ((balance - args.start_balance)/args.start_balance)*100,
        "max_drawdown_pct": max_dd_pct,
        "win_rate": win_rate,
        "trade_dates": display_df['Date'].tolist() if not display_df.empty else [],
        "trade_pnl": display_df['net_pnl'].tolist() if not display_df.empty else [],
        "trade_returns": display_df['return_pct'].tolist() if not display_df.empty else [],
        "trade_tickers": display_df['ticker'].tolist() if not display_df.empty else [],
        "trade_entries": display_df['entry_price'].tolist() if not display_df.empty else [],
        "trade_exits": display_df['exit_price'].tolist() if not display_df.empty else [],
        "trade_reasons": display_df['reason'].tolist() if not display_df.empty else [],
        "equity_curve": equity_curve
    }
    
    print(f"JSON_RESULT:{json.dumps(result_payload)}")

if __name__ == "__main__":
    args = parse_args()
    run_backtest(args)