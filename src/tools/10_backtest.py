import sys
import os
import argparse
import duckdb
import pandas as pd
import numpy as np
import json
from datetime import datetime, time
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# FIX APPLIED: Changed from parents[3] to parents[2]
# File is in: src/tools/10_backtest.py
# .parents[0] = tools
# .parents[1] = src
# .parents[2] = PROJECT ROOT (Where app.py lives)
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")

# ==============================================================================
# 2. ARGUMENT PARSING
# ==============================================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Quant OS v2.1 Backtester Engine")
    parser.add_argument("--start_date", type=str, required=True)
    parser.add_argument("--end_date", type=str, required=True)
    parser.add_argument("--start_balance", type=float, required=True)
    parser.add_argument("--pos_size_pct", type=float, required=True)
    parser.add_argument("--max_invest", type=float, required=True)
    parser.add_argument("--tax_rate", type=float, default=0.268)
    parser.add_argument("--atr_sensitivity", type=float, default=0.5)
    parser.add_argument("--trailing_stop_pct", type=float, default=0.25)
    parser.add_argument("--enforce_rth", type=str, default="False") 
    parser.add_argument("--archive_report", type=str, default="True")
    
    # Legacy args support
    parser.add_argument("--stop_period_days", type=str)
    parser.add_argument("--max_period_dd", type=str)
    
    return parser.parse_args()

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def run_backtest(args):
    enforce_rth = args.enforce_rth == "True"
    
    log.info(f"🚀 STARTING ENGINE | RTH: {enforce_rth} | Target: {args.start_date} to {args.end_date}")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. QUERY DATA
    query = f"""
        SELECT datetime_utc, open, high, low, close 
        FROM {config.TBL_INDICES} 
        WHERE ticker = 'SPX' 
          AND datetime_utc >= '{args.start_date}' 
          AND datetime_utc <= '{args.end_date} 23:59:59'
        ORDER BY datetime_utc ASC
    """
    try:
        df = con.execute(query).df()
    except Exception as e:
        log.error(f"❌ DB Read Failure: {e}")
        print(json.dumps({"error": str(e)}))
        return

    # 2. DATA AVAILABILITY CHECK (OBSERVABILITY)
    if df.empty:
        range_check = con.execute(f"SELECT min(datetime_utc), max(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker='SPX'").fetchone()
        
        db_start = range_check[0] if range_check else "N/A"
        db_end = range_check[1] if range_check else "N/A"
        
        err_msg = f"No Data in Range. Vault contains: {db_start} to {db_end}"
        log.error(f"❌ {err_msg}")
        
        print(json.dumps({"error": err_msg}))
        con.close()
        return

    con.close()

    # 3. TIMEZONE PREPARATION (TIMEZONE LAW: Force Naive UTC)
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_UTC)
    else:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
    
    # CRITICAL: Strip TZ to prevent WinError/DuckDB ambiguity (stores 15:00, not 10:00)
    df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)

    # 4. BACKTEST VARIABLES
    balance = args.start_balance
    position = 0 
    entry_price = 0.0
    entry_time = None
    trades = [] # Stores full trade objects
    equity_updates = [] # Stores balance after each trade
    
    # Indicators
    df['sma20'] = df['close'].rolling(20).mean()

    # 5. ITERATION
    log.info(f"📊 Analyzing {len(df)} candles...")
    
    for i in range(20, len(df)):
        row = df.iloc[i]
        curr_time = row['datetime_utc'] # Naive UTC
        price = row['close']
        
        # RTH Enforcement (Converts UTC time -> NY time for check)
        if enforce_rth:
            # We must *temporarily* localize to UTC to use tz_convert, then convert to NY
            # This is complex because curr_time is now Naive UTC, so we localize to UTC first.
            curr_time_aware = curr_time.tz_localize(config.TZ_UTC) 
            ny_time = curr_time_aware.tz_convert(config.TZ_NY).time()
            
            market_open = time(9, 30)
            market_close = time(16, 0)
            if not (market_open <= ny_time < market_close):
                continue 

        sma20 = row['sma20']
        
        # ENTRY (Close > SMA20)
        if position == 0 and price > sma20:
            invest_amt = min(balance * args.pos_size_pct, args.max_invest)
            shares = invest_amt / price
            position = shares
            entry_price = price
            entry_time = curr_time
            log.info(f"   🟢 OPEN LONG @ {price:.2f} ({curr_time})")

        # EXIT (Close < SMA20)
        elif position > 0:
            if price < sma20:
                proceeds = position * price
                raw_pnl = proceeds - (position * entry_price)
                
                tax_hit = raw_pnl * args.tax_rate if raw_pnl > 0 else 0
                net_pnl = raw_pnl - tax_hit
                
                balance += net_pnl
                
                # --- EQUITY TRACKING ---
                equity_updates.append(balance)
                
                trades.append({
                    'Entry Time': entry_time,
                    'Exit Time': curr_time,
                    'Entry Price': entry_price,
                    'Exit Price': price,
                    'Net PnL': net_pnl
                })
                position = 0
                log.info(f"   🔴 CLOSE @ {price:.2f} | PnL: {net_pnl:.2f}")

    # 6. REPORT GENERATION
    if not trades:
        print(json.dumps({"error": "No Trades Triggered (Strategy Logic)"}))
        return

    trades_df = pd.DataFrame(trades)
    
    # --- ADDED: PnL and Returns for plotting/table ---
    trades_df['RawReturn'] = (trades_df['Exit Price'] / trades_df['Entry Price'] - 1)
    
    # Display Conversion (Local PST)
    # NOTE: Since DB timestamps are now Naive UTC, we localize to UTC before converting to PST.
    trades_df['Entry Time PST'] = trades_df['Entry Time'].dt.tz_localize(config.TZ_UTC).dt.tz_convert(config.TZ_LOCAL)
    trades_df['Exit Time PST'] = trades_df['Exit Time'].dt.tz_localize(config.TZ_UTC).dt.tz_convert(config.TZ_LOCAL)
    
    trades_df['Date'] = trades_df['Entry Time PST'].dt.strftime('%Y-%m-%d %H:%M:%S')

    total_return = ((balance - args.start_balance) / args.start_balance) * 100
    win_rate = len(trades_df[trades_df['Net PnL'] > 0]) / len(trades_df) * 100
    
    # Pad the Equity Curve with start balance
    full_equity = [args.start_balance] + equity_updates
    
    # JSON Result
    result_payload = {
        "final_balance": balance,
        "total_return_pct": total_return,
        "max_drawdown_pct": 0.0, 
        "win_rate": win_rate,
        "total_trades": len(trades),
        
        # --- NEW DATA FOR GRAPH/TABLE ---
        "trade_dates": trades_df['Date'].tolist(),
        "trade_pnl": trades_df['Net PnL'].tolist(),
        "trade_returns": trades_df['RawReturn'].tolist(),
        "equity_curve": full_equity 
    }
    
    # Flush and Print
    for handler in log.handlers: handler.flush()
    print(f"JSON_RESULT:{json.dumps(result_payload)}")

if __name__ == "__main__":
    args = parse_args()
    run_backtest(args)