import sys
import os
import argparse
import duckdb
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File Location: src/core/engine_backtest.py
# Root Location: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")

# ==============================================================================
# 2. ARGUMENT PARSING
# ==============================================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Quant OS v2.5 Backtest Engine")
    
    # Date & Money
    parser.add_argument("--start_date", type=str, required=True)
    parser.add_argument("--end_date", type=str, required=True)
    parser.add_argument("--start_balance", type=float, required=True)
    parser.add_argument("--pos_size_pct", type=float, required=True)
    parser.add_argument("--max_invest", type=float, required=True)
    
    # Risk Management
    parser.add_argument("--tax_rate", type=float, default=0.268) # Section 1256
    parser.add_argument("--trailing_stop_pct", type=float, default=0.25)
    parser.add_argument("--ideal_gain_pct", type=float, default=0.0) 
    
    # Execution Logic
    parser.add_argument("--enforce_rth", type=str, default="True") 
    parser.add_argument("--archive_report", type=str, default="True")
    parser.add_argument("--selection_mode", type=str, default="FIRST", choices=["FIRST", "BEST"])
    parser.add_argument("--strike_offset", type=int, default=0)
    parser.add_argument("--skip_open_minutes", type=int, default=15) # The Hard Deck

    # v2.5 Roadmap Preparation (Straddle-Bias)
    parser.add_argument("--strategy_type", type=str, default="DIRECTIONAL", choices=["DIRECTIONAL", "STRADDLE"])

    return parser.parse_args()

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def construct_ticker(date_str, xsp_price, offset=0):
    """
    Constructs the XSP Option Ticker for a given date and price.
    Format: O:XSP{YYMMDD}C{00000000}
    """
    try:
        dt = pd.to_datetime(date_str)
        yymmdd = dt.strftime('%y%m%d')
        
        # Round to nearest integer for ATM strike
        atm_strike = int(round(xsp_price))
        target_strike = atm_strike + offset
        
        # Polygon Format: 8 digits, zero-padded, multiplied by 1000
        strike_str = f"{target_strike * 1000:08d}"
        
        # Currently defaults to Calls (C) as per Directional Strategy
        return f"O:XSP{yymmdd}C{strike_str}"
    except Exception as e:
        return None

def get_execution_start_time(signal_ts_ms, skip_minutes):
    """
    Returns the UTC timestamp of the 'Hard Deck' (Earliest allowed execution).
    Logic: Max(Signal Time, Market Open + Buffer)
    """
    # 1. Signal Time (UTC)
    sig_dt_utc = pd.to_datetime(signal_ts_ms, unit='ms', utc=True)
    
    # 2. Market Open for that day (09:30 ET)
    sig_dt_ny = sig_dt_utc.tz_convert(config.TZ_NY)
    market_open_ny = sig_dt_ny.replace(hour=9, minute=30, second=0, microsecond=0)
    
    # 3. The "Hard Deck" (Open + Buffer)
    hard_deck_ny = market_open_ny + timedelta(minutes=skip_minutes)
    
    # 4. Execution is the LATER of the two
    # Example: If signal is 10:00 and Deck is 09:45 -> Execute at 10:00
    # Example: If signal is 09:30 and Deck is 09:45 -> Execute at 09:45
    execution_start_ny = max(sig_dt_ny, hard_deck_ny)
    
    return execution_start_ny.tz_convert('UTC')

def simulate_real_outcome(df_opts, entry_price, trailing_stop_pct, ideal_gain_pct):
    """
    Simulates price action bar-by-bar to find Stop Loss or Take Profit.
    """
    highest_price = entry_price
    current_stop = entry_price * (1 - trailing_stop_pct)
    target_price = entry_price * (1 + ideal_gain_pct) if ideal_gain_pct > 0 else None
    
    for i, row in df_opts.iterrows():
        price_low = row['low']
        price_high = row['high']
        time_utc = row['datetime_utc']
        
        # Check Low against Stop (Pessimistic Check First)
        if price_low <= current_stop: 
            return current_stop, time_utc, "STOP_LOSS"
            
        # Check High against Target (Optimistic Check Second)
        if target_price and price_high >= target_price: 
            return target_price, time_utc, "TAKE_PROFIT"
        
        # Trail the Stop
        if price_high > highest_price:
            highest_price = price_high
            new_stop = highest_price * (1 - trailing_stop_pct)
            if new_stop > current_stop: 
                current_stop = new_stop
                
    # If Day Ends
    last_row = df_opts.iloc[-1]
    return last_row['close'], last_row['datetime_utc'], "EOD_EXIT"

# ==============================================================================
# 4. CORE ENGINE LOGIC
# ==============================================================================
def run_backtest(args):
    log.info(f"🚀 ENGINE START | Hard Deck: {args.skip_open_minutes}m | Mode: {args.selection_mode}")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. FETCH SIGNAL MANIFEST
    query_manifest = f"""
        SELECT * FROM {config.TBL_MANIFEST} 
        WHERE date BETWEEN '{args.start_date}' AND '{args.end_date}' 
        ORDER BY entry_timestamp_utc ASC
    """
    
    try: 
        manifest_df = con.execute(query_manifest).df()
    except Exception as e: 
        print(json.dumps({"error": f"DB Error: {str(e)}"}))
        return

    if manifest_df.empty:
        print(json.dumps({"error": "No Signals in Selected Window"}))
        return
    
    candidate_trades = []
    
    # 2. PROCESS SIGNALS
    for _, signal in manifest_df.iterrows():
        # A. Apply Hard Deck Law
        exec_start_utc = get_execution_start_time(signal['entry_timestamp_utc'], args.skip_open_minutes)
        sql_time_str = exec_start_utc.strftime('%Y-%m-%d %H:%M:%S')

        # B. Construct Ticker
        # TODO: v2.5 Upgrade - Add logic here for 'PUT' or 'STRADDLE' construction
        ticker = construct_ticker(signal['date'], signal['xsp_price'], args.strike_offset)
        if not ticker: continue

        # C. Query Option Data (Post-Hard Deck)
        opt_query = f"""
            SELECT datetime_utc, open, high, low, close 
            FROM {config.TBL_OPTIONS} 
            WHERE ticker = '{ticker}' 
            AND datetime_utc >= TIMESTAMP '{sql_time_str}' 
            ORDER BY datetime_utc ASC
        """
        
        try: df_opts = con.execute(opt_query).df()
        except: continue 
        
        if df_opts.empty: continue 
            
        # D. Execute Trade
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

    con.close()

    if not candidate_trades:
        print(json.dumps({"error": "No Executable Trades (Check Data availability or Hard Deck buffer)"}))
        return

    # 3. FILTER TRADES (Selection Mode)
    candidates_df = pd.DataFrame(candidate_trades)
    final_trades = []
    
    for day, group in candidates_df.groupby('Day'):
        if args.selection_mode == "BEST":
            # Hindsight optimization (for theoretical max)
            selected = group.sort_values('Return %', ascending=False).iloc[0]
            selected['Reason'] += " (Best)"
        else:
            # Reality (First executable signal)
            selected = group.sort_values('Entry Time').iloc[0]
        final_trades.append(selected)
        
    final_trades_df = pd.DataFrame(final_trades).sort_values('Entry Time')

    # 4. CALCULATE EQUITY CURVE
    balance = args.start_balance
    equity_curve = [balance]
    processed_trades = []
    
    # Re-connect for logging
    con = duckdb.connect(str(config.DB_FILE))
    
    for _, trade in final_trades_df.iterrows():
        if balance <= 0: break 
        
        # Position Sizing
        invest_target = balance * args.pos_size_pct
        invest_amt = max(0.0, min(invest_target, args.max_invest))
        
        if invest_amt < 10: continue # Minimum trade size safety

        # P&L Calculation
        pnl = invest_amt * trade['Return %']
        
        # Tax Drag (Section 1256)
        # Only tax profits. Losses reduce tax liability in reality, 
        # but for simple conservative backtest, we just don't tax losses.
        net_pnl = pnl - (pnl * args.tax_rate if pnl > 0 else 0)
        
        balance += net_pnl
        equity_curve.append(balance)
        
        processed_trades.append({
            'entry_time': trade['Entry Time'], 
            'ticker': trade['Ticker'],
            'net_pnl': net_pnl,
            'return_pct': trade['Return %'],
            'reason': trade['Reason'],
            'entry_price': trade['Entry Price'],
            'exit_price': trade['Exit Price']
        })

    # 5. LOGGING RESULTS TO DB
    if processed_trades and args.archive_report == "True":
        log_df = pd.DataFrame(processed_trades)
        
        # Ensure Naive Timestamps for DuckDB compatibility
        if log_df['entry_time'].dt.tz is not None:
             log_df['entry_time'] = log_df['entry_time'].dt.tz_convert('UTC').dt.tz_localize(None)

        con.execute(f"""
            CREATE TABLE IF NOT EXISTS active_simulation_log (
                entry_time TIMESTAMP, ticker VARCHAR, net_pnl DOUBLE, 
                return_pct DOUBLE, reason VARCHAR, entry_price DOUBLE, exit_price DOUBLE
            )
        """)
        con.execute("DELETE FROM active_simulation_log")
        con.execute("INSERT INTO active_simulation_log SELECT * FROM log_df")

    con.close()

    # 6. JSON OUTPUT (For Interface)
    display_df = pd.DataFrame(processed_trades)
    
    if not display_df.empty:
        # Convert to Local Time string for UI Display
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
    
    # The Interface looks for this specific Tag to parse JSON
    print(f"JSON_RESULT:{json.dumps(result_payload)}")

if __name__ == "__main__":
    args = parse_args()
    run_backtest(args)