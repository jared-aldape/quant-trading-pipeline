import duckdb
import pandas as pd
import numpy as np
import sys
import pytz
from datetime import datetime, timedelta
from pathlib import Path

# ==========================================
# 0. GLOBAL PATH SETUP
# ==========================================
current_file = Path(__file__).resolve()
project_root = current_file.parent
sys.path.append(str(project_root))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("Backtester")

# ==========================================
# 1. PARAMETERS
# ==========================================
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
REPORTS_DIR = config.PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FILE = REPORTS_DIR / f"backtest_v2.5_final_{TIMESTAMP}.csv"

# Simulation Settings
STARTING_BALANCE = 600.00 
START_DATE = "2025-11-01" 
END_DATE = datetime.now().strftime("%Y-%m-%d")

# --- RISK MANAGEMENT INSTITUTION ---
POSITION_SIZE_PCT = 0.75 
MAX_INVESTMENT_DOLLAR = 5250.00 

USE_ATR_STOP = True
ATR_PERIOD = 20
ATR_SENSITIVITY = 0.5
TRAILING_STOP_PCT = 0.25

# Execution Rules
ENFORCE_RTH = False 

# Times (UTC for Logic, PST for Display)
PST_TZ = config.TZ_LOCAL
RTH_START_PST = datetime.strptime("06:30", "%H:%M").time()
RTH_END_PST = datetime.strptime("13:00", "%H:%M").time()

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

def run_simulation(enforce_rth_flag):
    log.info(f"--- 📈 Starting Backtest (v2.5 Final Report) ---")
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. FETCH TRADES
    query = f"""
    SELECT * FROM {config.TBL_MANIFEST} 
    WHERE date BETWEEN '{START_DATE}' AND '{END_DATE}' 
    ORDER BY entry_timestamp_utc ASC
    """
    try:
        trades_df = con.execute(query).df()
    except Exception as e:
        log.error(f"❌ Error reading manifest: {e}")
        return

    if trades_df.empty:
        log.error("❌ No trades found in manifest.")
        return

    # --- TRADE INTEGRITY FILTER (Single Trade Per Day) ---
    initial_count = len(trades_df)
    trades_df['date_key'] = trades_df['date'].astype(str)
    trades_df = trades_df.sort_values(by=['date_key', 'entry_timestamp_utc'], ascending=True)
    trades_df.drop_duplicates(subset=['date_key'], keep='first', inplace=True)
    trades_df.drop(columns=['date_key'], inplace=True)
    log.info(f"📝 Removed {initial_count - len(trades_df)} redundant signals. Trades remaining: {len(trades_df)}")
    
    # 2. LOAD SPX CONTEXT
    log.info("📥 Loading SPX Context for ATR...")
    spx_full = con.execute(f"SELECT datetime_utc, high, low, close FROM {config.TBL_INDICES} WHERE ticker='SPX' ORDER BY datetime_utc ASC").df()
    
    spx_full = ensure_utc(spx_full, 'datetime_utc')
    spx_full = calculate_atr(spx_full, ATR_PERIOD)

    history = []
    balance = STARTING_BALANCE
    peak_balance = STARTING_BALANCE
    
    counts = {"Total": len(trades_df), "Traded": 0, "NEP_RTH": 0, "NEP_DATA": 0}

    log.info(f"🔄 Simulating {len(trades_df)} unique signals...")

    for _, trade in trades_df.iterrows():
        entry_ts_ms = trade['entry_timestamp_utc']
        entry_dt = pd.to_datetime(entry_ts_ms, unit='ms', utc=True)
        entry_pst = entry_dt.astimezone(PST_TZ).time()
        
        # Default empty/skipped trade values
        empty_record = {
            "Date": entry_dt.date(), "Ticker": "-", "Start Balance": balance, "Investment": 0.0,
            "Entry Time": entry_pst.strftime("%H:%M"), "Entry Price": 0.0, "Peak Price": 0.0,
            "Exit Time": entry_pst.strftime("%H:%M"), "Exit Price": 0.0, 
            "P&L $": 0.0, "ROI %": 0.0, "New Balance": balance, "Drawdown %": 0.0, "Result": "NEP"
        }

        # RTH Filter
        if enforce_rth_flag:
            if not (RTH_START_PST <= entry_pst <= RTH_END_PST):
                counts["NEP_RTH"] += 1
                history.append({**empty_record, "Drawdown %": (balance - peak_balance) / peak_balance * 100, "Result": "NEP (Outside RTH)"})
                continue

        # Get Ticker
        ticker = get_ticker(trade['date'], trade['xsp_price'])
        
        # Get Option Data
        opt_q = f"""
        SELECT datetime_utc, open, high, low, close 
        FROM {config.TBL_OPTIONS} 
        WHERE ticker = '{ticker}' 
          AND datetime_utc >= to_timestamp({entry_ts_ms}/1000)
        ORDER BY datetime_utc ASC
        """
        bars = con.execute(opt_q).df()
        bars = ensure_utc(bars, 'datetime_utc')
        
        if bars.empty:
            counts["NEP_DATA"] += 1
            history.append({**empty_record, "Ticker": ticker, "Drawdown %": (balance - peak_balance) / peak_balance * 100, "Result": "NEP (No Data)"})
            continue

        # Execute
        counts["Traded"] += 1
        entry_price = bars.iloc[0]['close']
        
        # INVESTMENT LOGIC
        invest_target = balance * POSITION_SIZE_PCT
        invest = min(invest_target, MAX_INVESTMENT_DOLLAR)

        # ATR Stop Logic
        current_atr_row = spx_full[spx_full['datetime_utc'] <= entry_dt]
        current_atr = current_atr_row.iloc[-1]['atr'] if not current_atr_row.empty else 1.0
        atr_stop_dist = current_atr * ATR_SENSITIVITY
        hard_stop = entry_price - atr_stop_dist if USE_ATR_STOP else 0.0
        
        exit_price = 0.0
        reason = "EOD"
        max_price = entry_price
        
        for _, bar in bars.iterrows():
            if bar['high'] > max_price: max_price = bar['high']
            trail_stop = max_price * (1 - TRAILING_STOP_PCT)
            effective_stop = max(hard_stop, trail_stop)
            
            if bar['low'] <= effective_stop:
                exit_price = effective_stop
                reason = "STOP"
                break
        
        if exit_price == 0.0:
            exit_price = bars.iloc[-1]['close'] 
            
        # P&L
        shares = invest / entry_price
        pnl = (exit_price - entry_price) * shares
        final_roi = (exit_price - entry_price) / entry_price
        
        new_balance = balance + pnl
        if new_balance > peak_balance: peak_balance = new_balance
        dd = (new_balance - peak_balance) / peak_balance * 100
        
        # --- SUCCESSFUL TRADE APPEND (FULL SCHEMA) ---
        history.append({
            "Date": entry_dt.date(),
            "Ticker": ticker,
            "Start Balance": balance,
            "Investment": invest,
            "Entry Time": entry_dt.astimezone(PST_TZ).strftime("%H:%M"),
            "Entry Price": entry_price,
            "Peak Price": max_price,
            "Exit Time": bars.iloc[-1]['datetime_utc'].astimezone(PST_TZ).strftime("%H:%M") if exit_price == bars.iloc[-1]['close'] else entry_dt.astimezone(PST_TZ).strftime("%H:%M"),
            "Exit Price": exit_price,
            "P&L $": pnl,
            "ROI %": final_roi * 100,
            "New Balance": new_balance,
            "Drawdown %": dd,
            "Result": reason
        })
        balance = new_balance

    con.close()
    
    # --- REPORTING ---
    log.info(f"📝 Breakdown: Total={counts['Total']} | Traded={counts['Traded']} | RTH-Skip={counts['NEP_RTH']} | Data-Skip={counts['NEP_DATA']}")
    
    if not history:
        log.warning("No history generated.")
        return

    results = pd.DataFrame(history)
    results.to_csv(REPORT_FILE, index=False)
    
    active = results[results['Result'].isin(['STOP', 'EOD'])]
    win_rate = len(active[active['P&L $'] > 0]) / len(active) * 100 if not active.empty else 0
    
    if 'Drawdown %' in results.columns and not results['Drawdown %'].isnull().all():
        max_dd = results['Drawdown %'].min()
    else:
        max_dd = 0.0
    
    final_balance = results.iloc[-1]['New Balance']
    total_return_pct = (final_balance - STARTING_BALANCE) / STARTING_BALANCE * 100

    print("\n" + "="*40)
    print(f"📊 BACKTEST RESULTS (v2.5)")
    print("="*40)
    print(f"Start:   ${STARTING_BALANCE:,.2f}")
    print(f"End:     ${final_balance:,.2f}")
    print(f"Return:  {total_return_pct:+.1f}%")
    print(f"Max DD:  {max_dd:.1f}%")
    print(f"Win Rate:{win_rate:.1f}%")
    print(f"Trades:  {len(active)}")
    print(f"Saved:   {REPORT_FILE}")
    print("="*40)

if __name__ == "__main__":
    run_simulation(ENFORCE_RTH)