import duckdb
import pandas as pd
import numpy as np
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SignalScanner")

def calculate_technicals(df):
    """
    Applies VIX technical indicators (Standard MACD & Wilder's RSI).
    """
    # --- MACD (12, 26, 9) ---
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    
    df['vix_macd'] = ema12 - ema26
    df['vix_signal'] = df['vix_macd'].ewm(span=9, adjust=False).mean()
    df['vix_hist'] = df['vix_macd'] - df['vix_signal']
    
    # --- RSI (14) Wilder's ---
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False, min_periods=14).mean()
    ma_down = down.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = ma_up / ma_down
    df['vix_rsi'] = 100 - (100 / (1 + rs))
    
    return df

def scan_signals():
    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. CLEAR OLD DATA
    con.execute(f"DELETE FROM {config.TBL_MANIFEST}")
    log.info("🧹 Cleared old manifest entries.")

    # 2. LOAD VIX DATA
    log.info("📈 Loading VIX data...")
    try:
        vix_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker = 'VIX' ORDER BY datetime_utc ASC").df()
    except Exception as e:
        log.error(f"❌ Database Error: {e}")
        return

    if vix_df.empty:
        log.error("❌ No VIX data found! Run Phase 3 (Ingest) first.")
        return

    # 3. CALCULATE INDICATORS
    vix_df = calculate_technicals(vix_df)
    
    # 4. DETECT SIGNALS
    # Signal: Bearish Cross (Hist goes positive -> negative)
    vix_df['prev_hist'] = vix_df['vix_hist'].shift(1)
    signal_mask = (vix_df['vix_hist'] < 0) & (vix_df['prev_hist'] > 0)
    signals = vix_df[signal_mask].copy()
    
    log.info(f"🔎 Detected {len(signals)} signals.")
    
    # 5. GENERATE MANIFEST
    if not signals.empty:
        manifest_data = pd.DataFrame()
        
        # FIX: Convert Microseconds (from DB) to Milliseconds (for PK)
        # datetime64[us] -> int64 gives microseconds. Divide by 1000 -> milliseconds.
        manifest_data['entry_timestamp_utc'] = signals['datetime_utc'].astype('int64') // 1000
        
        manifest_data['date'] = signals['datetime_utc'].dt.date
        manifest_data['signal_type'] = 'VIX_MACD_BEAR_CROSS'
        manifest_data['vix_close'] = signals['close']
        manifest_data['vix_rsi'] = signals['vix_rsi']
        manifest_data['vix_macd'] = signals['vix_macd']
        manifest_data['xsp_price'] = 0.0 # Placeholder

        # Write to DB
        con.register('df_signals', manifest_data)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM df_signals")
        log.info(f"✅ Wrote {len(manifest_data)} signals to Manifest.")
            
    con.close()

if __name__ == "__main__":
    scan_signals()