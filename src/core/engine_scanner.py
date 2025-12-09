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
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
# 3. HELPER FUNCTIONS
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

    if df.empty: return df

    df['datetime_utc'] = pd.to_datetime(df['datetime_utc']).dt.tz_localize(pytz.utc)
    df['datetime_et'] = df['datetime_utc'].dt.tz_convert(config.TZ_NY)
    df = df.set_index('datetime_utc') 
    return df

def save_manifest(signals):
    con = duckdb.connect(str(config.DB_FILE))
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
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
    if signals:
        signals_df = pd.DataFrame(signals)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM signals_df")
        log.info(f"💾 Manifest Rebuilt: {len(signals_df)} Signals (Hedged Protocol).")
    else:
        log.info("💾 Manifest Rebuilt: 0 Signals found.")
    con.close()

# ==============================================================================
# 4. MAIN SCANNER LOGIC
# ==============================================================================
def scan_and_generate_manifest():
    log.info("📡 Scanning for VIX Fractal Flow (Smart Scale Logic)...")
    
    spx_df = fetch_intraday_data('SPX')
    vix_df = fetch_intraday_data('VIX')
    
    if spx_df.empty or vix_df.empty:
        log.error("❌ Missing SPX or VIX data. Aborting scan.")
        return

    # Indicators
    vix_1h_df = strat_fractal.calculate_macd(vix_df.resample('1h').last().dropna())
    vix_5m_df = strat_fractal.calculate_macd(vix_df.resample('5min').last().dropna())
    vix_5m_df = strat_fractal.calculate_rsi(vix_5m_df, window=14)
    
    signals = []
    days = spx_df['datetime_et'].dt.date.unique()
    last_signal_time = None

    print(f"\n{'DATE':<12} | {'TYPE':<8} | {'STATUS':<15} | {'TARGET'}")
    print("-" * 70)

    for date in days:
        day_open = config.TZ_NY.localize(datetime.combine(date, OPEN_TIME_ET))
        day_close = config.TZ_NY.localize(datetime.combine(date, CLOSE_TIME_ET))
        hard_deck = day_open + timedelta(minutes=15)
        
        daily_bars = vix_df[(vix_df['datetime_et'] >= day_open) & (vix_df['datetime_et'] <= day_close)]
        
        for ts_current in daily_bars.index:
            if ts_current < hard_deck: continue
            if last_signal_time and (ts_current - last_signal_time).total_seconds()/60 < COOLDOWN_MINUTES: continue

            ts_5m = ts_current.floor('5min')
            if ts_5m not in vix_5m_df.index: continue
            current_rsi = vix_5m_df.loc[ts_5m, 'rsi']

            result = strat_fractal.check_fractal_flow(vix_1h_df, vix_5m_df, ts_current, current_rsi)
            
            if result['signal_type']:
                try:
                    raw_price = spx_df['close'].asof(ts_current)
                    
                    # --- 🧠 SMART SCALE FIX ---
                    # If price > 2000, it is real SPX (6000) -> Divide by 10 to get XSP (600)
                    # If price < 2000, it is SPY Proxy (600) -> Use as is for XSP (600)
                    if raw_price > 2000:
                        xsp_est = raw_price / 10.0
                    else:
                        xsp_est = raw_price
                    # ---------------------------

                except: continue

                if xsp_est > 0:
                    sig_type_str = f"VIX_FRACTAL_{'LONG' if result['signal_type']=='call' else 'SHORT'}"
                    
                    signals.append({
                        'date': date,
                        'entry_timestamp_utc': int(ts_current.timestamp() * 1000),
                        'signal_type': sig_type_str,
                        'xsp_price': xsp_est,
                        'trade_type': result['signal_type'],
                        'meta_data': result['reason'],
                        'allocation_pct': 1.0 
                    })
                    
                    last_signal_time = ts_current
                    print(f"{str(date):<12} | {result['signal_type'].upper():<8} | {'✅ TRIGGERED':<15} | Strike: {int(xsp_est)}")

    print("-" * 70)
    save_manifest(signals)

if __name__ == '__main__':
    scan_and_generate_manifest()