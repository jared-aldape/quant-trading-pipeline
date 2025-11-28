import sys
import os
import argparse
import duckdb
import pandas as pd
import numpy as np
import json
from datetime import datetime, time, timedelta
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
    
    # RISK SETTINGS
    parser.add_argument("--trailing_stop_pct", type=float, default=0.25) # 25% Stop
    parser.add_argument("--ideal_gain_pct", type=float, default=0.0) 
    
    parser.add_argument("--enforce_rth", type=str, default="False") 
    parser.add_argument("--archive_report", type=str, default="True")
    
    # NEW: Selection Mode
    parser.add_argument("--selection_mode", type=str, default="FIRST", choices=["FIRST", "BEST"], 
                        help="FIRST: Take first signal of day. BEST: Take highest PnL signal of day.")
    
    return parser.parse_args()

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def construct_ticker(date_str, xsp_price):
    try:
        dt = pd.to_datetime(date_str)
        yymmdd = dt.strftime('%y%m%d')
        strike = int(round(xsp_price))
        strike_str = f"{strike * 1000:08d}"
        return f"O:XSP{yymmdd}C{strike_str}"
    except:
        return None

def simulate_real_outcome(df_opts, entry_price, trailing_stop_pct, ideal_gain_pct):
    """
    Simulates trade outcome based on 1-minute bars.
    Returns: Exit Price, Exit Time, Exit Reason
    """
    highest_price = entry_price
    current_stop = entry_price * (1 - trailing_stop_pct)
    target_price = entry_price * (1 + ideal_gain_pct) if ideal_gain_pct > 0 else None
    
    for i, row in df_opts.iterrows():
        price_low = row['low']
        price_high = row['high']
        time_utc = row['datetime_utc']
        
        # A. Check TARGET (Take Profit)
        if target_price and price_high >= target_price:
            return target_price, time_utc, "TARGET"

        # B. Check STOP (Trailing)
        if price_low <= current_stop:
            return current_stop, time_utc, "STOP"
        
        # C. Update Trailing Stop (High Water Mark)
        if price_high > highest_price:
            highest_price = price_high
            new_stop = highest_price * (1 - trailing_stop_pct)
            if new_stop > current_stop:
                current_stop = new_stop
                
    last_row = df_opts.iloc[-1]
    return last_row['close'], last_row['datetime_utc'], "EOD"

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def run_backtest(args):
    log.info(f"🚀 REAL DATA ENGINE | Mode: {args.selection_mode}")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. FETCH SIGNALS
    query_manifest = f"""
        SELECT * FROM {config.TBL_MANIFEST}
        WHERE date BETWEEN '{args.start_date}' AND '{args.end_date}'
        ORDER BY entry_timestamp_utc ASC
    """
    try:
        manifest_df = con.execute(query_manifest).df()
    except Exception as e:
        log.error(f"Manifest Query Failed: {e}")
        print(json.dumps({"error": "DB Error"}))
        return

    if manifest_df.empty:
        print(json.dumps({"error": "No Signals in Manifest"}))
        return

    # --------------------------------------------------------------------------
    # PHASE 1: SIMULATE ALL CANDIDATES (Hypothetical)
    # --------------------------------------------------------------------------
    candidate_trades = []
    
    # Pre-fetch check
    opt_table_exists = False
    try:
        con.execute(f"SELECT 1 FROM {config.TBL_OPTIONS} LIMIT 1")
        opt_table_exists = True
    except: pass

    if not opt_table_exists:
        print(json.dumps({"error": "Option Data Missing. Run Tool 3 first."}))
        return
    
    for _, signal in manifest_df.iterrows():
        ticker = construct_ticker(signal['date'], signal['xsp_price'])
        entry_time_ms = signal['entry_timestamp_utc']
        
        # Fetch Data for this specific signal
        opt_query = f"""
            SELECT datetime_utc, open, high, low, close
            FROM {config.TBL_OPTIONS}
            WHERE ticker = '{ticker}'
              AND datetime_utc >= to_timestamp({entry_time_ms}/1000)
            ORDER BY datetime_utc ASC
        """
        try:
            df_opts = con.execute(opt_query).df()
        except: continue 
        
        if df_opts.empty: continue 
            
        entry_price = df_opts.iloc[0]['close']
        entry_time = df_opts.iloc[0]['datetime_utc']
        
        # Simulate Outcome
        exit_price, exit_time, reason = simulate_real_outcome(
            df_opts, 
            entry_price, 
            args.trailing_stop_pct, 
            args.ideal_gain_pct
        )
        
        roi_pct = (exit_price - entry_price) / entry_price
        
        candidate_trades.append({
            'Entry Time': entry_time,
            'Exit Time': exit_time,
            'Ticker': ticker,
            'Entry Price': entry_price,
            'Exit Price': exit_price,
            'Return %': roi_pct,
            'Reason': reason,
            'Day': pd.to_datetime(entry_time).date()
        })

    con.close()

    if not candidate_trades:
        print(json.dumps({"error": "No Valid Trades Found (Check Data)"}))
        return

    # --------------------------------------------------------------------------
    # PHASE 2: FILTER TRADES (The Selection Logic)
    # --------------------------------------------------------------------------
    candidates_df = pd.DataFrame(candidate_trades)
    final_trades = []
    
    # Group by Day to enforce "Single Trade Per Day"
    for day, group in candidates_df.groupby('Day'):
        if args.selection_mode == "FIRST":
            # Select the trade with the earliest Entry Time
            selected = group.sort_values('Entry Time').iloc[0]
        elif args.selection_mode == "BEST":
            # Select the trade with the Highest Return %
            selected = group.sort_values('Return %', ascending=False).iloc[0]
        else:
            selected = group.iloc[0] # Fallback
            
        final_trades.append(selected)
        
    final_trades_df = pd.DataFrame(final_trades).sort_values('Entry Time')

    # --------------------------------------------------------------------------
    # PHASE 3: CALCULATE EQUITY CURVE (Real Money)
    # --------------------------------------------------------------------------
    balance = args.start_balance
    equity_curve = [balance]
    processed_trades = []
    
    for _, trade in final_trades_df.iterrows():
        if balance <= 0: break # Bankruptcy Stop

        # Position Sizing
        invest_target = balance * args.pos_size_pct
        invest_amt = min(invest_target, args.max_invest)
        invest_amt = max(0.0, invest_amt)
        
        if invest_amt == 0: continue

        # PnL
        pnl = invest_amt * trade['Return %']
        tax_hit = pnl * args.tax_rate if pnl > 0 else 0
        net_pnl = pnl - tax_hit
        
        balance += net_pnl
        equity_curve.append(balance)
        
        processed_trades.append({
            'Entry Time': trade['Entry Time'],
            'Exit Time': trade['Exit Time'],
            'Ticker': trade['Ticker'],
            'Entry Price': trade['Entry Price'],
            'Exit Price': trade['Exit Price'],
            'Net PnL': net_pnl,
            'Return %': trade['Return %'], 
            'Reason': trade['Reason']
        })

    # --------------------------------------------------------------------------
    # PHASE 4: REPORTING
    # --------------------------------------------------------------------------
    if args.archive_report == "True":
        try:
            report_df = pd.DataFrame(processed_trades)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_REAL_{args.selection_mode}_{timestamp}.csv"
            report_df.to_csv(config.REPORTS_DIR / filename, index=False)
        except: pass

    display_df = pd.DataFrame(processed_trades)
    if not display_df.empty:
        # Convert to Local Time for Display
        display_df['Date'] = display_df['Entry Time'].dt.tz_localize(config.TZ_UTC).dt.tz_convert(config.TZ_LOCAL).dt.strftime('%Y-%m-%d %H:%M')
        win_rate = len(display_df[display_df['Net PnL'] > 0]) / len(display_df) * 100
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
        "trade_pnl": display_df['Net PnL'].tolist() if not display_df.empty else [],
        "trade_returns": display_df['Return %'].tolist() if not display_df.empty else [],
        "trade_tickers": display_df['Ticker'].tolist() if not display_df.empty else [],
        "trade_entries": display_df['Entry Price'].tolist() if not display_df.empty else [],
        "trade_exits": display_df['Exit Price'].tolist() if not display_df.empty else [],
        "trade_reasons": display_df['Reason'].tolist() if not display_df.empty else [],
        "equity_curve": equity_curve
    }
    
    print(f"JSON_RESULT:{json.dumps(result_payload)}")

if __name__ == "__main__":
    args = parse_args()
    run_backtest(args)