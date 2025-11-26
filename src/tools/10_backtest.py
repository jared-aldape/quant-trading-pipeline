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
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# We are in: quant-trading-pipeline/src/tools/
# We need to reach: quant-trading-pipeline/ (Root)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Add Root to System Path to allow imports from 'src.utils'
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
    
    log.info(f"🚀 STARTING ENGINE | RTH: {enforce_rth} | Range: {args.start_date} to {args.end_date}")
    
    # 1. LOAD DATA (INTEGRITY LAW)
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
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
        return
    finally:
        con.close()

    if df.empty:
        log.error("❌ No Data Found in Range.")
        return

    # 2. TIMEZONE PREPARATION (TIMEZONE LAW)
    # The DB is confirmed UTC. We ensure Pandas knows this.
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_UTC)
    else:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)

    # 3. BACKTEST VARIABLES
    balance = args.start_balance
    position = 0 
    entry_price = 0.0
    entry_time = None
    trades = []
    
    # ATR Calculation
    df['tr'] = np.maximum((df['high'] - df['low']), 
                          np.maximum(abs(df['high'] - df['close'].shift(1)), 
                                     abs(df['low'] - df['close'].shift(1))))
    df['atr'] = df['tr'].rolling(14).mean()

    log.info(f"📊 Analyzing {len(df)} candles...")

    # 4. ITERATION
    for i in range(15, len(df)):
        row = df.iloc[i]
        curr_time = row['datetime_utc'] # UTC
        price = row['close']
        
        # --- RTH ENFORCEMENT ---
        if enforce_rth:
            # Convert UTC -> NY Time for the check
            ny_time = curr_time.tz_convert(config.TZ_NY).time()
            market_open = time(9, 30)
            market_close = time(16, 0)
            
            if not (market_open <= ny_time < market_close):
                continue 

        # --- SIGNAL LOGIC (Sample Trend) ---
        sma20 = df['close'].iloc[i-20:i].mean()
        
        # ENTRY
        if position == 0 and price > sma20:
            invest_amt = min(balance * args.pos_size_pct, args.max_invest)
            shares = invest_amt / price
            position = shares
            entry_price = price
            entry_time = curr_time
            # OBSERVABILITY LAW: Log the trade
            log.info(f"   🟢 OPEN LONG @ {price:.2f} ({curr_time})")

        # EXIT
        elif position > 0:
            if price < sma20:
                proceeds = position * price
                raw_pnl = proceeds - (position * entry_price)
                
                # TAX AWARE COMPOUNDING
                tax_hit = raw_pnl * args.tax_rate if raw_pnl > 0 else 0
                net_pnl = raw_pnl - tax_hit
                
                balance += net_pnl
                
                trades.append({
                    'Entry Time': entry_time, # Store as UTC object
                    'Exit Time': curr_time,   # Store as UTC object
                    'Entry Price': entry_price,
                    'Exit Price': price,
                    'Net PnL': net_pnl
                })
                
                position = 0
                # OBSERVABILITY LAW: Log the trade
                log.info(f"   🔴 CLOSE @ {price:.2f} | PnL: {net_pnl:.2f}")

    # 5. REPORT GENERATION
    if not trades:
        # JSON Output for Dashboard to catch
        print(json.dumps({"error": "No Trades"}))
        return

    trades_df = pd.DataFrame(trades)
    
    # --- TIMEZONE LAW: DISPLAY CONVERSION ---
    # Convert Internal UTC -> Local PST for the Human Report
    trades_df['Entry Time'] = trades_df['Entry Time'].dt.tz_convert(config.TZ_LOCAL)
    trades_df['Exit Time'] = trades_df['Exit Time'].dt.tz_convert(config.TZ_LOCAL)
    
    # Format for CSV
    trades_df['Entry Time'] = trades_df['Entry Time'].dt.strftime('%Y-%m-%d %H:%M:%S %Z')
    trades_df['Exit Time'] = trades_df['Exit Time'].dt.strftime('%Y-%m-%d %H:%M:%S %Z')

    total_return = ((balance - args.start_balance) / args.start_balance) * 100
    win_rate = len(trades_df[trades_df['Net PnL'] > 0]) / len(trades_df) * 100
    
    # Save Report
    if args.archive_report == "True":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = config.REPORTS_DIR / f"backtest_report_{timestamp}.csv"
        trades_df.to_csv(report_path, index=False)
        log.info(f"📝 Report Saved: {report_path.name}")

    # 6. JSON OUPUT FOR DASHBOARD
    result_payload = {
        "final_balance": balance,
        "total_return_pct": total_return,
        "max_drawdown_pct": 0.0, 
        "win_rate": win_rate,
        "total_trades": len(trades)
    }
    
    # Flush logs before printing JSON
    for handler in log.handlers:
        handler.flush()
        
    print(f"JSON_RESULT:{json.dumps(result_payload)}")

if __name__ == "__main__":
    args = parse_args()
    run_backtest(args)