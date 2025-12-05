import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, time, timedelta
import pytz

# ==============================================================================
# 0. ENVIRONMENT PATCH (WINDOWS COMPATIBILITY)
# ==============================================================================
# CRITICAL: Force UTF-8 Encoding to allow "Vibe Code" Emojis (📡, ✅) on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception as e:
        print(f"⚠️ Warning: Could not force UTF-8 encoding. Emojis may fail. {e}")

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import strat_fractal

log = get_logger("SignalScanner")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
COOLDOWN_MINUTES = 60
OPEN_TIME_ET = time(9, 30)
CLOSE_TIME_ET = time(16, 0)

# ==============================================================================
# 3. HELPER FUNCTIONS (Data & Persistence)
# ==============================================================================
def fetch_intraday_data(ticker):
    """Fetches intraday data from the Vault (DuckDB)."""
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    query = f"""
        SELECT datetime_utc, close, open, high, low
        FROM {config.TBL_INDICES} 
        WHERE ticker = '{ticker}' 
        ORDER BY datetime_utc ASC
    """
    try:
        df = con.execute(query).df()
    except Exception as e:
        log.error(f"❌ Failed to fetch {ticker}: {e}")
        return pd.DataFrame()
    finally:
        con.close()

    if df.empty:
        return df

    # Timezone Handling (UTC -> ET for RTH Logic)
    df['datetime_utc'] = pd.to_datetime(df['datetime_utc']).dt.tz_localize(pytz.utc)
    df['datetime_et'] = df['datetime_utc'].dt.tz_convert(config.TZ_NY)
    df = df.set_index('datetime_utc') # Index must be UTC for calculations
    return df

def save_manifest(signals):
    """Writes the generated signals to the Trade Manifest table."""
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Reset Table
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
    
    # 2. Recreate Schema (Updated for v3.1 Hedged Protocol)
    con.execute(f"""
        CREATE TABLE {config.TBL_MANIFEST} (
            date DATE,
            entry_timestamp_utc BIGINT,
            signal_type VARCHAR,
            xsp_price DOUBLE,
            trade_type VARCHAR,
            meta_data VARCHAR,
            allocation_pct DOUBLE
        )
    """)

    # 3. Insert Data
    if signals:
        signals_df = pd.DataFrame(signals)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM signals_df")
        log.info(f"💾 Manifest Rebuilt: {len(signals_df)} Signals (Hedged Protocol).")
    else:
        log.info("💾 Manifest Rebuilt: 0 Signals found.")
    
    con.close()

# ==============================================================================
# 4. MAIN SCANNER LOGIC (FRACTAL FLOW)
# ==============================================================================
def scan_and_generate_manifest():
    log.info("📡 Scanning for VIX Fractal Flow (Hedged Protocol)...")
    
    # 1. Fetch & Prep Data
    spx_df = fetch_intraday_data('SPX')
    vix_df = fetch_intraday_data('VIX')
    
    if spx_df.empty or vix_df.empty:
        log.error("❌ Missing SPX or VIX data. Aborting scan.")
        return

    # 2. Calculate Indicators
    # We use the centralized strat_fractal logic
    vix_1h_df = strat_fractal.calculate_macd(vix_df.resample('1h').last().dropna())
    vix_5m_df = strat_fractal.calculate_macd(vix_df.resample('5min').last().dropna())
    
    # NEW: Calculate RSI for the Gatekeeper Law
    vix_5m_df = strat_fractal.calculate_rsi(vix_5m_df, window=14)
    
    # 3. Scan Loop
    signals = []
    days = spx_df['datetime_et'].dt.date.unique()
    last_signal_time = None

    print(f"\n{'DATE':<12} | {'TYPE':<8} | {'STATUS':<15} | {'NOTES'}")
    print("-" * 70)

    for date in days:
        # Define RTH Window
        day_open = config.TZ_NY.localize(datetime.combine(date, OPEN_TIME_ET))
        day_close = config.TZ_NY.localize(datetime.combine(date, CLOSE_TIME_ET))
        hard_deck = day_open + timedelta(minutes=15)
        
        # Get bars for the day
        daily_bars = vix_df[(vix_df['datetime_et'] >= day_open) & (vix_df['datetime_et'] <= day_close)]
        
        for ts_current in daily_bars.index:
            # Check Hard Deck
            if ts_current < hard_deck: continue
            
            # Check Cooldown
            if last_signal_time and (ts_current - last_signal_time).total_seconds()/60 < COOLDOWN_MINUTES:
                continue

            # Get RSI (Align to 5m)
            ts_5m = ts_current.floor('5min')
            if ts_5m not in vix_5m_df.index: continue
            current_rsi = vix_5m_df.loc[ts_5m, 'rsi']

            # Check Signal (Fractal + RSI Gatekeeper)
            result = strat_fractal.check_fractal_flow(vix_1h_df, vix_5m_df, ts_current, current_rsi)
            
            if result['signal_type']:
                # Lookup SPX Price
                try:
                    spx_price = spx_df['close'].asof(ts_current)
                    xsp_est = spx_price / 10.0 # Scaling Law
                except: continue

                if xsp_est > 0:
                    # LOGIC CHANGE: Dynamic Signal Detection
                    # We write the specific DETECTED signal (Call or Put)
                    
                    sig_type_str = f"VIX_FRACTAL_{'LONG' if result['signal_type']=='call' else 'SHORT'}"
                    
                    signals.append({
                        'date': date,
                        'entry_timestamp_utc': int(ts_current.timestamp() * 1000),
                        'signal_type': sig_type_str,
                        'xsp_price': xsp_est,
                        'trade_type': result['signal_type'], # 'call' or 'put'
                        'meta_data': result['reason'],
                        'allocation_pct': 1.0 # 100% allocation to the detected signal
                    })
                    
                    last_signal_time = ts_current
                    print(f"{str(date):<12} | {result['signal_type'].upper():<8} | {'✅ TRIGGERED':<15} | {result['reason']}")

    print("-" * 70)

    # 4. Persistence
    save_manifest(signals)

if __name__ == '__main__':
    scan_and_generate_manifest()