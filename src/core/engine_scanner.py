import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import sys
from pathlib import Path
import pytz
import json

# ==============================================================================
# 1. SETUP & INTEGRATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
import src.core.strat_fractal as strategy

# ⚡ IMPORT THE FEDERATED BRAINS
try:
    from src.core.engine_chop_guard import chop_engine
except ImportError: chop_engine = None

try:
    from src.core.engine_ml_precision import predict_success
except ImportError: predict_success = None

log = get_logger("SignalScanner")
TBL_MANIFEST = "trade_manifest"
TBL_MACRO = getattr(config, 'TBL_MACRO_FLOW', 'macro_flow_state')

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def filter_rth(df):
    """Filters signals to Regular Trading Hours (09:30 - 16:00 ET)."""
    if df.empty: return df
    # Ensure UTC awareness
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC')
        
    est = pytz.timezone('America/New_York')
    df['dt_est'] = df['datetime_utc'].dt.tz_convert(est)
    mask = (df['dt_est'].dt.time >= time(9, 30)) & (df['dt_est'].dt.time < time(16, 0))
    return df[mask].drop(columns=['dt_est']).copy()

def get_macro_context(con, target_date):
    """Fetches the 20-Day Flow Bias for a specific date."""
    try:
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if TBL_MACRO not in tables: return "NEUTRAL"
        
        q = f"SELECT flow_bias FROM {TBL_MACRO} WHERE date <= '{target_date}' ORDER BY date DESC LIMIT 1"
        res = con.execute(q).fetchone()
        return res[0] if res else "NEUTRAL"
    except: return "NEUTRAL"

# ==============================================================================
# 3. MAIN SCANNER LOGIC (THE TRIAGE)
# ==============================================================================
def run_scanner(lookback_days=30):
    log.info(f"🔎 INITIATING SIGNAL SCAN (XSP) | Lookback: {lookback_days} days")
    
    if not config.DB_FILE.exists(): 
        log.error("❌ DB File Not Found")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. INIT SCHEMA
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TBL_MANIFEST} (
            entry_timestamp_utc BIGINT PRIMARY KEY, 
            date DATE, 
            signal_type VARCHAR, 
            xsp_price DOUBLE, 
            trade_type VARCHAR, 
            meta_data VARCHAR, 
            allocation_pct DOUBLE
        )
    """)

    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    # 2. FETCH RAW DATA
    try:
        vix_df = con.execute(f"SELECT datetime_utc, close, high, low FROM indices_1m WHERE ticker='VIX' AND datetime_utc >= '{start_date}' ORDER BY datetime_utc").df()
        xsp_df = con.execute(f"SELECT datetime_utc, close, high, low FROM indices_1m WHERE ticker='XSP' AND datetime_utc >= '{start_date}' ORDER BY datetime_utc").df()
        log.info(f"   Loaded Data: VIX ({len(vix_df)}), XSP ({len(xsp_df)})")
    except Exception as e:
        log.error(f"❌ Extraction Failed: {e}"); con.close(); return

    if len(vix_df) < 200:
        log.warning("⚠️ Insufficient Data. Run Pipeline."); con.close(); return

    # 3. NORMALIZE TIMESTAMPS (CRITICAL FIX)
    # Force everything to be UTC-Aware immediately to prevent mismatches later
    vix_df['datetime_utc'] = pd.to_datetime(vix_df['datetime_utc'])
    xsp_df['datetime_utc'] = pd.to_datetime(xsp_df['datetime_utc'])
    
    if vix_df['datetime_utc'].dt.tz is None:
        vix_df['datetime_utc'] = vix_df['datetime_utc'].dt.tz_localize('UTC')
    if xsp_df['datetime_utc'].dt.tz is None:
        xsp_df['datetime_utc'] = xsp_df['datetime_utc'].dt.tz_localize('UTC')
    
    # 4. GENERATE RAW FRACTALS
    all_signals = strategy.apply_fractal_logic(vix_df, xsp_df)
    log.info(f"   Raw Signals: {len(all_signals)}")
    
    all_signals = filter_rth(all_signals)
    
    # 5. APPLY THE TRIAGE PROTOCOL
    valid_signals = []
    
    if not all_signals.empty:
        log.info("🛡️ Applying TRIAGE (Chop + Macro + ML)...")
        
        for i, row in all_signals.iterrows():
            sig_time = row['datetime_utc']
            sig_date = sig_time.date()
            trade_type = 'CALL' if row['signal'] == 1 else 'PUT'
            
            # --- FILTER 1: PHYSICS (Chop Guard) ---
            market_state = "UNKNOWN"
            if chop_engine:
                # Context window: 50 bars leading up to signal
                # ⚡ NOW SAFE: Both sides are UTC-Aware
                context = xsp_df[xsp_df['datetime_utc'] <= sig_time].tail(50)
                market_state = chop_engine.analyze(context)
                
                if market_state == "CHOP":
                    continue # 🛑 REJECT: Theta Kill Zone
            
            # --- FILTER 2: THE TIDE (Macro Flow) ---
            flow_bias = get_macro_context(con, sig_date)
            
            # --- FILTER 3: THE ORACLE (ML Precision) ---
            ml_score = 50.0
            if predict_success:
                ml_score = predict_success(
                    signal_type="BULL" if trade_type == 'CALL' else "BEAR",
                    vix_val=row.get('close_vix', 15.0), 
                    rsi_val=row.get('vix_rsi', 50.0),
                    market_regime=market_state,
                    flow_bias=flow_bias
                )
            
            # ⚡ DECISION GATE
            if ml_score >= 55.0 or market_state == "CRITICAL_SQUEEZE":
                meta = f"State: {market_state} | Flow: {flow_bias} | ML: {ml_score:.1f}%"
                alloc = 2.0 if ml_score > 70 else 1.0
                
                row['trade_type'] = trade_type
                row['meta_data'] = meta
                row['allocation_pct'] = alloc
                valid_signals.append(row)
            
        all_signals = pd.DataFrame(valid_signals)
        log.info(f"   Survived Triage: {len(all_signals)}")

    if all_signals.empty:
        log.info("🏁 Scan complete. 0 Signals survived Triage.")
        con.close(); return

    # 6. COMMIT TO VAULT
    unique_dates = all_signals['datetime_utc'].dt.date.unique()
    date_list = "', '".join([d.strftime('%Y-%m-%d') for d in unique_dates])
    
    con.execute(f"DELETE FROM {TBL_MANIFEST} WHERE date IN ('{date_list}')")

    count = 0
    for i, row in all_signals.iterrows():
        ts_bigint = int(row['datetime_utc'].timestamp() * 1000)
        sig_name = "BULL_FRACTAL" if row['trade_type'] == 'CALL' else "BEAR_FRACTAL"
        
        con.execute(f"INSERT OR IGNORE INTO {TBL_MANIFEST} VALUES (?, ?, ?, ?, ?, ?, ?)", 
                    [ts_bigint, row['datetime_utc'].date(), sig_name, float(row['close']), 
                     row['trade_type'], row['meta_data'], row['allocation_pct']])
        count += 1

    log.info(f"🏁 SCAN COMPLETE. {count} High-Precision Signals Saved.")
    con.close()

if __name__ == "__main__":
    run_scanner(lookback_days=30)