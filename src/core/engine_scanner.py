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
    
    # Ensure UTC awareness if missing
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC')
    else:
        # If already aware (e.g. NY), convert back to UTC first to be safe
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC')
    
    # Create NY column for filtering
    df['dt_ny'] = df['datetime_utc'].dt.tz_convert(config.TZ_NY)
    
    # RTH Logic
    df = df.set_index('dt_ny')
    df = df.between_time("09:30", "16:00")
    df = df.reset_index()
    return df

def get_macro_bias(con, target_date_str):
    """Fetches the macro flow state (BULL/BEAR) for the day."""
    try:
        res = con.execute(f"SELECT flow_bias FROM {TBL_MACRO} WHERE date <= '{target_date_str}' ORDER BY date DESC LIMIT 1").fetchone()
        return res[0] if res else "NEUTRAL"
    except:
        return "NEUTRAL"

# ==============================================================================
# 3. CORE ENGINE
# ==============================================================================
def run_scanner(lookback_days=30):
    log.info(f"🔎 INITIATING SIGNAL SCAN (XSP) | Lookback: {lookback_days} days")
    
    if not config.DB_FILE.exists():
        log.error("❌ Database not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. FETCH DATA (Indices only)
    start_dt = (datetime.now() - timedelta(days=lookback_days + 5)).strftime('%Y-%m-%d')
    
    df = con.execute(f"""
        SELECT datetime_utc, open, high, low, close, ticker 
        FROM {config.TBL_INDICES} 
        WHERE datetime_utc >= '{start_dt}'
        ORDER BY datetime_utc ASC
    """).df()
    
    if df.empty:
        log.warning("⚠️ No data found for scanning.")
        con.close(); return

    # ⚡ CRITICAL FIX: FORCE UTC AWARENESS ON RAW DATA
    # This aligns the DB data (Naive) with the Strategy Signals (Aware)
    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC')

    # 2. SEPARATE STREAMS
    xsp = df[df['ticker'] == 'XSP'].copy()
    vix = df[df['ticker'] == 'VIX'].copy()
    
    if xsp.empty or vix.empty:
        log.warning("⚠️ Missing XSP or VIX data stream.")
        con.close(); return

    log.info(f"   Loaded Data: VIX ({len(vix)}), XSP ({len(xsp)})")

    # 3. APPLY STRATEGY (The Fractal Engine)
    if hasattr(strategy, 'apply_fractal_logic'):
        # Pass copies to prevent SettingWithCopy warnings inside strat
        signals_df = strategy.apply_fractal_logic(vix.copy(), xsp.copy())
    elif hasattr(strategy, 'generate_signals'):
        signals_df = strategy.generate_signals(xsp.copy(), vix.copy())
    else:
        log.error("❌ Strategy file incompatible (missing entry point).")
        con.close(); return
    
    # 4. FILTER RTH (No overnight noise)
    signals_df = filter_rth(signals_df)
    
    # 5. TRIAGE & ML SCORING
    valid_signals = []
    
    if not signals_df.empty:
        log.info(f"   Raw Signals: {len(signals_df)}")
        log.info("🛡️ Applying TRIAGE (Chop + Macro + ML)...")

        for _, row in signals_df.iterrows():
            if row['signal'] == 0: continue
            
            ts = row['datetime_utc']
            trade_type = "CALL" if row['signal'] == 1 else "PUT"
            
            # A. MACRO FILTER
            date_str = ts.strftime('%Y-%m-%d')
            flow_bias = get_macro_bias(con, date_str)
            
            # B. CHOP GUARD
            market_state = "TREND"
            if chop_engine:
                # ⚡ COMPARISON FIX: Both 'xsp' and 'ts' are now UTC Aware.
                context_slice = xsp[xsp['datetime_utc'] <= ts].tail(50)
                if len(context_slice) >= 20:
                    try:
                        res = chop_engine.analyze(context_slice)
                        if res == "TRENDING": market_state = "TREND"
                        elif res == "CHOP": market_state = "CHOP"
                        elif res == "CRITICAL_SQUEEZE": market_state = "CRITICAL_SQUEEZE"
                    except Exception: pass
            
            # C. ML PRECISION
            ml_score = 50.0
            if predict_success:
                try:
                    vix_val = row.get('close_vix', 15.0) 
                    rsi_val = row.get('vix_rsi', 50.0)
                    ml_score = predict_success(
                        signal_type="BULL" if trade_type == 'CALL' else "BEAR",
                        vix_val=vix_val,
                        rsi_val=rsi_val
                    )
                except Exception: ml_score = 50.0

            # D. SELECTION LOGIC
            accept = False
            
            # Macro Alignment
            if (trade_type == 'CALL' and flow_bias == 'BULL') or \
               (trade_type == 'PUT' and flow_bias == 'BEAR'):
                accept = True
                
            # ML Override
            if ml_score > 65.0:
                accept = True
                
            # Hard Chop Veto
            if market_state == 'CHOP' and ml_score < 80.0:
                accept = False

            if accept:
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
                    (ts_bigint, row['datetime_utc'].strftime('%Y-%m-%d'), sig_name, row['close'], row['trade_type'], row['meta_data'], row['allocation_pct']))
        count += 1
        
    con.close()
    log.info(f"🏁 SCAN COMPLETE. {count} High-Precision Signals Saved.")

if __name__ == "__main__":
    run_scanner()