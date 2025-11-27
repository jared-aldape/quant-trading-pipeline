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
    parser = argparse.ArgumentParser(description="Quant OS v2.2 Backtester Engine")
    parser.add_argument("--start_date", type=str, required=True)
    parser.add_argument("--end_date", type=str, required=True)
    parser.add_argument("--start_balance", type=float, required=True)
    parser.add_argument("--pos_size_pct", type=float, required=True)
    parser.add_argument("--max_invest", type=float, required=True)
    parser.add_argument("--tax_rate", type=float, default=0.268)
    
    # RISK SETTINGS
    parser.add_argument("--atr_sensitivity", type=float, default=0.5)
    parser.add_argument("--trailing_stop_pct", type=float, default=0.005) # 0.5% Index move ~= 25% Option move
    parser.add_argument("--ideal_gain_pct", type=float, default=0.0) # 0.4 = 40% Target
    
    parser.add_argument("--enforce_rth", type=str, default="False") 
    parser.add_argument("--archive_report", type=str, default="True")
    parser.add_argument("--selection_mode", type=str, default="FIRST", choices=["FIRST", "BEST"])
    parser.add_argument("--leverage", type=float, default=50.0) # Default to 50x (Options Sim)
    
    return parser.parse_args()

# ==============================================================================
# 3. HELPER: SOPHISTICATED TRADE SIMULATOR
# ==============================================================================
def simulate_trade_outcome(entry_idx, df, trailing_stop_pct, atr_val, atr_sens, leverage, ideal_gain_pct):
    """
    Simulates a trade with:
    1. ATR Hard Stop (Risk Floor) - From v2.5
    2. Trailing Stop (Greed Management) - From v2.5
    3. Profit Target (Ideal Gain) - New
    """
    entry_price = df.iloc[entry_idx]['close']
    
    # 1. Establish Risk Floor (ATR Hard Stop)
    # This mimics the "Hard Stop" from the old script
    hard_stop_price = entry_price - (atr_val * atr_sens)
    
    # 2. Establish Profit Target (Scaled by Leverage)
    target_price = None
    if ideal_gain_pct > 0:
        # If target is +40% Option Gain, and Leverage is 50x:
        # Required Index Move = 0.40 / 50 = 0.008 (0.8%)
        required_index_move = ideal_gain_pct / leverage
        target_price = entry_price * (1 + required_index_move)

    highest_price = entry_price
    current_stop = hard_stop_price
    
    # Scan forward candle-by-candle
    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        price = row['close']
        time_utc = row['datetime_utc']
        
        # A. Check TARGET HIT (Take Profit)
        if target_price and price >= target_price:
            return price, time_utc, i, "TARGET"

        # B. Check STOP HIT (Effective Stop)
        if price < current_stop:
            return current_stop, time_utc, i, "STOP"
        
        # C. Update Trailing Stop (High Water Mark)
        if price > highest_price:
            highest_price = price
            
            # Calculate the Trailing Level
            # Note: trailing_stop_pct here applies to the INDEX price
            trail_level = highest_price * (1 - trailing_stop_pct)
            
            # The Effective Stop takes the TIGHTER of the Hard Stop or the Trailing Stop
            # (Just like v2.5: effective_stop = max(hard_stop, trail_stop))
            new_stop = max(hard_stop_price, trail_level)
            
            if new_stop > current_stop:
                current_stop = new_stop
                
        # D. Force Close EOD
        if i == len(df) - 1:
            return price, time_utc, i, "EOD"
            
    return entry_price, df.iloc[entry_idx]['datetime_utc'], entry_idx, "ERR"

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def run_backtest(args):
    enforce_rth = args.enforce_rth == "True"
    
    log.info(f"🚀 ENGINE START | Lev: {args.leverage}x | Target: {args.ideal_gain_pct*100}%")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. QUERY INDEX DATA (Fast)
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
    con.close()

    if df.empty:
        print(json.dumps({"error": "No Data in Range"}))
        return

    # 2. PREP & INDICATORS
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_UTC)
    else:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
    df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)

    # --- CALCULATE ATR (From v2.5) ---
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean() # Standard ATR Period
    df['sma20'] = df['close'].rolling(20).mean()

    # --------------------------------------------------------------------------
    # PHASE 1: SCAN CANDIDATES
    # --------------------------------------------------------------------------
    candidate_trades = []
    
    for i in range(20, len(df)):
        row = df.iloc[i]
        price = row['close']
        curr_time = row['datetime_utc']
        
        if enforce_rth:
            ny_time = curr_time.tz_localize(config.TZ_UTC).tz_convert(config.TZ_NY).time()
            if not (time(9, 30) <= ny_time < time(16, 0)): continue

        # SIGNAL LOGIC (Placeholder for your complex logic)
        is_signal = price > row['sma20'] and df.iloc[i-1]['close'] <= df.iloc[i-1]['sma20']
        
        if is_signal:
            # Get current ATR for the stop calculation
            atr_val = row['atr'] if not np.isnan(row['atr']) else price * 0.005
            
            # RUN SIMULATION
            exit_price, exit_time, exit_idx, reason = simulate_trade_outcome(
                i, df, 
                args.trailing_stop_pct, 
                atr_val, 
                args.atr_sensitivity,
                args.leverage,
                args.ideal_gain_pct
            )
            
            # Calculate Returns
            raw_return = (exit_price - price) / price
            leveraged_return = raw_return * args.leverage
            
            candidate_trades.append({
                'entry_idx': i,
                'Entry Time': curr_time,
                'Exit Time': exit_time,
                'Entry Price': price,
                'Exit Price': exit_price,
                'RawReturn': raw_return,
                'LevReturn': leveraged_return,
                'Reason': reason,
                'Day': curr_time.date()
            })

    if not candidate_trades:
        print(json.dumps({"error": "No Signals Found"}))
        return

    # --------------------------------------------------------------------------
    # PHASE 2: FILTER & EQUITY
    # --------------------------------------------------------------------------
    candidates_df = pd.DataFrame(candidate_trades)
    final_trades = []
    
    for day, group in candidates_df.groupby('Day'):
        if args.selection_mode == "FIRST":
            selected = group.sort_values('Entry Time').iloc[0]
        elif args.selection_mode == "BEST":
            selected = group.sort_values('LevReturn', ascending=False).iloc[0]
        else: selected = group.iloc[0]
        final_trades.append(selected)
    
    final_trades_df = pd.DataFrame(final_trades).sort_values('Entry Time')

    balance = args.start_balance
    equity_curve = [balance]
    processed_trades = []
    
    for _, trade in final_trades_df.iterrows():
        invest_amt = min(balance * args.pos_size_pct, args.max_invest)
        
        pnl = invest_amt * trade['LevReturn']
        
        # Apply Tax
        tax_hit = pnl * args.tax_rate if pnl > 0 else 0
        net_pnl = pnl - tax_hit
        
        balance += net_pnl
        equity_curve.append(balance)
        
        processed_trades.append({
            'Entry Time': trade['Entry Time'],
            'Exit Time': trade['Exit Time'],
            'Entry Price': trade['Entry Price'],
            'Exit Price': trade['Exit Price'],
            'Net PnL': net_pnl,
            'Return %': trade['LevReturn'], 
            'Reason': trade['Reason']
        })

    # REPORTING
    if args.archive_report == "True":
        try:
            report_df = pd.DataFrame(processed_trades)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_{args.selection_mode}_{timestamp}.csv"
            report_df.to_csv(config.REPORTS_DIR / filename, index=False)
        except: pass

    # METRICS
    display_df = pd.DataFrame(processed_trades)
    display_df['Date'] = display_df['Entry Time'].dt.tz_localize(config.TZ_UTC).dt.tz_convert(config.TZ_LOCAL).dt.strftime('%Y-%m-%d %H:%M')
    
    equity_s = pd.Series(equity_curve)
    drawdown = (equity_s - equity_s.cummax()) / equity_s.cummax()
    
    result_payload = {
        "final_balance": balance,
        "total_return_pct": ((balance - args.start_balance)/args.start_balance)*100,
        "max_drawdown_pct": drawdown.min() * 100,
        "win_rate": len(display_df[display_df['Net PnL'] > 0]) / len(display_df) * 100 if len(display_df) > 0 else 0,
        "trade_dates": display_df['Date'].tolist(),
        "trade_pnl": display_df['Net PnL'].tolist(),
        "trade_returns": display_df['Return %'].tolist(),
        "equity_curve": equity_curve
    }
    
    print(f"JSON_RESULT:{json.dumps(result_payload)}")

if __name__ == "__main__":
    args = parse_args()
    run_backtest(args)