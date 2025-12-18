import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import sys
from pathlib import Path
import pytz

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
import src.core.strat_fractal as strategy

log = get_logger("SignalScanner")
TBL_MANIFEST = getattr(config, 'TBL_MANIFEST', 'option_signal_manifest')

def filter_rth(df):
    if df.empty: return df
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC')
    est = pytz.timezone('America/New_York')
    df['dt_est'] = df['datetime_utc'].dt.tz_convert(est)
    mask = (df['dt_est'].dt.time >= time(9, 30)) & (df['dt_est'].dt.time < time(16, 0))
    return df[mask].drop(columns=['dt_est']).copy()

# UPDATED: Now accepts 'lookback_days' to override the 5-day default
def run_scanner(lookback_days=5):
    log.info(f"🔎 INITIATING SIGNAL SCAN (XSP) | Lookback: {lookback_days} days")
    
    if not config.DB_FILE.exists(): return
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. SCHEMA ASSURANCE
    con.execute(f"CREATE TABLE IF NOT EXISTS {TBL_MANIFEST} (entry_timestamp_utc BIGINT PRIMARY KEY, date DATE, signal_type VARCHAR, xsp_price DOUBLE, trade_type VARCHAR, meta_data VARCHAR, allocation_pct DOUBLE)")

    # 2. DATA EXTRACTION
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    try:
        vix_df = con.execute(f"SELECT datetime_utc, close FROM indices_1m WHERE ticker='VIX' AND datetime_utc >= '{start_date}' ORDER BY datetime_utc").df()
        xsp_df = con.execute(f"SELECT datetime_utc, close FROM indices_1m WHERE ticker='XSP' AND datetime_utc >= '{start_date}' ORDER BY datetime_utc").df()
    except Exception as e:
        log.error(f"❌ Extraction Failed: {e}"); con.close(); return

    if len(vix_df) < 500:
        log.warning(f"⚠️ Insufficient VIX data ({len(vix_df)} rows). Need at least 500 for MACD stabilization."); con.close(); return

    # 3. STRATEGY EXECUTION
    vix_df['datetime_utc'] = pd.to_datetime(vix_df['datetime_utc'])
    xsp_df['datetime_utc'] = pd.to_datetime(xsp_df['datetime_utc'])
    
    all_signals = strategy.apply_fractal_logic(vix_df, xsp_df)
    all_signals = filter_rth(all_signals)

    if all_signals.empty:
        log.info("🏁 Scan complete. No Fractal flips found in the RTH window.")
        log.info(f"   [VIX SNAPSHOT] Latest Close: {vix_df['close'].iloc[-1]:.2f}")
        con.close(); return

    # 4. VAULT INTEGRATION
    unique_dates = all_signals['datetime_utc'].dt.date.unique()
    date_list_str = "', '".join([d.strftime('%Y-%m-%d') for d in unique_dates])
    con.execute(f"DELETE FROM {TBL_MANIFEST} WHERE date IN ('{date_list_str}')")

    count = 0
    for i, row in all_signals.iterrows():
        ts_bigint = int(pd.to_datetime(row['datetime_utc']).timestamp() * 1000)
        sig_name = "BULL_FRACTAL" if row['signal'] == 1 else "BEAR_FRACTAL"
        con.execute(f"INSERT OR IGNORE INTO {TBL_MANIFEST} VALUES (?, ?, ?, ?, ?, ?, ?)", 
                    [ts_bigint, row['datetime_utc'].date(), sig_name, float(row['close']), 
                     'CALL' if row['signal'] == 1 else 'PUT', 'Fractal Crossover (RTH)', 1.0])
        count += 1

    log.info(f"🏁 SCAN COMPLETE. {count} signals committed to manifest.")
    con.close()

if __name__ == "__main__":
    run_scanner(lookback_days=5)