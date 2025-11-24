import duckdb
import pandas as pd
import numpy as np
import sys
import argparse
import json
from datetime import datetime
from pathlib import Path

# ==========================================
# 0. GLOBAL PATH SETUP & CONFIGS
# ==========================================
current_file = Path(__file__).resolve()
project_root = current_file.parent
sys.path.append(str(project_root))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("Backtester")

# ==========================================
# 1. ARGUMENT PARSING
# ==========================================
def str2bool(v):
    if isinstance(v, bool): return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'): return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'): return False
    else: raise argparse.ArgumentTypeError('Boolean value expected.')

def parse_arguments():
    parser = argparse.ArgumentParser()
    # Financial Inputs
    parser.add_argument('--start_balance', type=float, default=600.00)
    parser.add_argument('--pos_size_pct', type=float, default=0.75)
    parser.add_argument('--max_invest', type=float, default=5250.00)
    parser.add_argument('--tax_rate', type=float, default=0.268)
    
    # Risk Inputs
    parser.add_argument('--stop_period_days', type=int, default=4)
    parser.add_argument('--max_period_dd', type=float, default=0.30)
    
    # Technical Stop Inputs
    parser.add_argument('--use_atr_stop', type=str2bool, default=True)
    parser.add_argument('--atr_period', type=int, default=20)
    parser.add_argument('--atr_sensitivity', type=float, default=0.5)
    parser.add_argument('--trailing_stop_pct', type=float, default=0.25)
    
    # Execution Filters & Archiving
    parser.add_argument('--enforce_rth', type=str2bool, default=False)
    parser.add_argument('--archive_report', type=str2bool, default=True) # NEW TOGGLE
    parser.add_argument('--start_date', type=str, default="2025-11-01")
    parser.add_argument('--end_date', type=str, default=datetime.now().strftime("%Y-%m-%d"))
    return parser.parse_args()

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def calculate_atr(df, period=20):
    df = df.copy()
    df['high_low'] = df['high'] - df['low']
    df['high_prev_close'] = np.abs(df['high'] - df['close'].shift(1))
    df['low_prev_close'] = np.abs(df['low'] - df['close'].shift(1))
    df['true_range'] = df[['high_low', 'high_prev_close', 'low_prev_close']].max(axis=1)
    df['atr'] = df['true_range'].ewm(alpha=1/period, adjust=False).mean()
    return df

def get_ticker(date_val, xsp_price):
    if isinstance(date_val, str): d = pd.to_datetime(date_val)
    else: d = date_val
    date_str = d.strftime("%y%m%d")
    strike = int(round(xsp_price))
    strike_str = f"{strike * 1000:08d}"
    return f"O:XSP{date_str}C{strike_str}"

def ensure_utc(df, col_name='datetime_utc'):
    if df.empty: return df
    df[col_name] = pd.to_datetime(df[col_name])
    if df[col_name].dt.tz is None:
        df[col_name] = df[col_name].dt.tz_localize('UTC')
    else:
        df[col_name] = df[col_name].dt.tz_convert('UTC')
    return df

# ==========================================
# 3. CORE SIMULATION
# ==========================================
def run_simulation(args):
    PST_TZ = config.TZ_LOCAL
    
    # Setup Reporting Directory
    REPORTS_DIR = project_root / "reports"
    REPORTS_DIR.mkdir(exist_ok=True)
    
    log.info(f"--- 📈 Starting Backtest ({args.start_date} to {args.end_date}) ---")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    query = f"SELECT * FROM {config.TBL_MANIFEST} WHERE date BETWEEN '{args.start_date}' AND '{args.end_date}' ORDER BY entry_timestamp_utc ASC"
    try:
        trades_df = con.execute(query).df()
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return

    if not trades_df.empty:
        trades_df['date_key'] = trades_df['date'].astype(str)
        trades_df = trades_df.sort_values(by=['date_key', 'entry_timestamp_utc'], ascending=True)
        trades_df.drop_duplicates(subset=['date_key'], keep='first', inplace=True)
        trades_df.drop(columns=['date_key'], inplace=True)
    
    spx_full = con.execute(f"SELECT datetime_utc, high, low, close FROM {config.TBL_INDICES} WHERE ticker='SPX' ORDER BY datetime_utc ASC").df()
    spx_full = ensure_utc(spx_full, 'datetime_utc')
    spx_full = calculate_atr(spx_full, args.atr_period)

    history = []
    balance = args.start_balance
    peak_balance = args.start_balance
    risk_bucket_start_balance = balance
    risk_bucket_day_counter = 0
    
    RTH_START = datetime.strptime("06:30", "%H:%M").time()
    RTH_END = datetime.strptime("13:00", "%H:%M").time()

    # --- 🖨️ PRINT TABLE HEADER ---
    header_fmt = "{:<12} | {:<12} | {:<8} | {:<8} | {:<12} | {:<12}"
    print("-" * 80)
    print(header_fmt.format("DATE", "START BAL", "ENTRY", "EXIT", "NET GAIN %", "END BAL"))
    print("-" * 80)

    for _, trade in trades_df.iterrows():
        entry_ts_ms = trade['entry_timestamp_utc']
        entry_dt = pd.to_datetime(entry_ts_ms, unit='ms', utc=True)
        entry_pst_time = entry_dt.astimezone(PST_TZ).strftime("%H:%M")
        entry_date_str = entry_dt.date().strftime("%Y-%m-%d")
        
        risk_bucket_day_counter += 1
        period_drawdown = (balance - risk_bucket_start_balance) / risk_bucket_start_balance
        
        skip_trade_risk = False
        if period_drawdown <= -args.max_period_dd:
            skip_trade_risk = True
        
        if risk_bucket_day_counter >= args.stop_period_days:
            risk_bucket_day_counter = 0
            risk_bucket_start_balance = balance 

        if skip_trade_risk:
            print(header_fmt.format(entry_date_str, f"${balance:,.2f}", "-", "-", "SKIPPED", f"${balance:,.2f}"))
            continue 

        if args.enforce_rth:
            entry_time_obj = entry_dt.astimezone(PST_TZ).time()
            if not (RTH_START <= entry_time_obj <= RTH_END):
                continue

        ticker = get_ticker(trade['date'], trade['xsp_price'])
        opt_q = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= to_timestamp({entry_ts_ms}/1000) ORDER BY datetime_utc ASC"
        bars = con.execute(opt_q).df()
        bars = ensure_utc(bars, 'datetime_utc')
        
        if bars.empty:
            continue

        entry_price = bars.iloc[0]['close']
        invest = min(balance * args.pos_size_pct, args.max_invest)
        shares = invest / entry_price
        
        current_atr = spx_full[spx_full['datetime_utc'] <= entry_dt].iloc[-1]['atr'] if not spx_full.empty else 1.0
        hard_stop = entry_price - (current_atr * args.atr_sensitivity) if args.use_atr_stop else 0.0
        
        exit_price = 0.0
        reason = "EOD"
        max_price = entry_price
        exit_dt_obj = bars.iloc[-1]['datetime_utc'] 
        
        for _, bar in bars.iterrows():
            if bar['high'] > max_price: max_price = bar['high']
            trail_stop = max_price * (1 - args.trailing_stop_pct)
            effective_stop = max(hard_stop, trail_stop)
            
            if bar['low'] <= effective_stop:
                exit_price = effective_stop
                exit_dt_obj = bar['datetime_utc']
                reason = "STOP"
                break
        
        if exit_price == 0.0: exit_price = bars.iloc[-1]['close']
        
        exit_pst_time = exit_dt_obj.astimezone(PST_TZ).strftime("%H:%M")

        gross_pnl = (exit_price - entry_price) * shares
        tax_deducted = gross_pnl * args.tax_rate if gross_pnl > 0 else 0.0
        net_pnl = gross_pnl - tax_deducted
        net_trade_roi = (net_pnl / invest * 100) if invest > 0 else 0.0

        start_bal_display = balance 
        new_balance = balance + net_pnl
        
        if new_balance > peak_balance: peak_balance = new_balance
        dd = (new_balance - peak_balance) / peak_balance * 100
        
        history.append({
            "Date": entry_dt.date(),
            "Ticker": ticker,
            "Start Balance": start_bal_display,
            "Investment": invest,
            "Entry Time": entry_pst_time,
            "Entry Price": entry_price,
            "Peak Price": max_price,
            "Exit Time": exit_pst_time,
            "Exit Price": exit_price,
            "Gross P&L $": gross_pnl,
            "Tax Deducted $": tax_deducted,
            "Net P&L $": net_pnl,
            "ROI %": net_trade_roi,
            "New Balance": new_balance,
            "Drawdown %": dd,
            "Result": reason
        })

        pnl_str = f"{net_trade_roi:+.2f}%"
        print(header_fmt.format(
            entry_date_str, 
            f"${start_bal_display:,.2f}", 
            entry_pst_time, 
            exit_pst_time, 
            pnl_str, 
            f"${new_balance:,.2f}"
        ))

        balance = new_balance

    con.close()
    
    if not history:
        print("JSON_RESULT:" + json.dumps({"error": "No trades found"}))
        return

    results = pd.DataFrame(history)
    final_bal = results.iloc[-1]['New Balance']
    total_ret = (final_bal - args.start_balance) / args.start_balance * 100
    max_dd = results['Drawdown %'].min()
    
    active = results[results['Result'].isin(['STOP', 'EOD'])]
    win_rate = len(active[active['Net P&L $'] > 0]) / len(active) * 100 if not active.empty else 0.0

    print("-" * 80) 

    # --- ARCHIVE REPORT LOGIC ---
    if args.archive_report:
        cols_to_save = [
            "Date", "Ticker", "Start Balance", "Investment", 
            "Entry Time", "Entry Price", "Peak Price", 
            "Exit Time", "Exit Price", 
            "Gross P&L $", "Tax Deducted $", "Net P&L $", 
            "ROI %", "New Balance", "Drawdown %", "Result"
        ]
        final_cols = [c for c in cols_to_save if c in results.columns]
        results = results[final_cols]
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"backtest_report_{timestamp}.csv"
        results.to_csv(report_path, index=False)
        log.info(f"📝 Report archived: {report_path.name}")
    else:
        log.info("⏩ Archiving skipped (Quick Report Mode)")

    output_payload = {
        "final_balance": final_bal,
        "total_return_pct": total_ret,
        "max_drawdown_pct": max_dd,
        "win_rate": win_rate
    }
    print("JSON_RESULT:" + json.dumps(output_payload))

if __name__ == "__main__":
    args = parse_arguments()
    run_simulation(args)