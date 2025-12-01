import sys
import duckdb
import pandas as pd
import pandas_ta as ta
import numpy as np
from pathlib import Path
from datetime import datetime, date, timedelta
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SignalScanner")

# ==============================================================================
# 2. CONFIGURATION (ACTIVE TRADER MODE)
# ==============================================================================
# "The Active Protocol"
# Adjusted to increase frequency while avoiding the RSI > 40 "Danger Zone".
VIX_RSI_THRESHOLD = 30  # Relaxed from 22 to Standard 30
VIX_RSI_PERIOD = 10     # Sensitive (Was 14). Reacts faster to dips.
COOLDOWN_MINUTES = 30   # Prevents signal spamming on the same day

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def get_market_calendar(start_date, end_date):
    """
    Generates a list of expected trading days (Business Days - Holidays).
    """
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return pd.date_range(start=start_date, end=end_date, freq=us_bd).date

def fetch_intraday_data(ticker):
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    query = f"""
        SELECT datetime_utc, close 
        FROM {config.TBL_INDICES} 
        WHERE ticker = '{ticker}' 
        ORDER BY datetime_utc ASC
    """
    try:
        df = con.execute(query).df()
        if not df.empty:
            df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
            # Ensure UTC per Timezone Law
            if df['datetime_utc'].dt.tz is None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_UTC)
            else:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
    except Exception as e:
        log.error(f"Failed to fetch {ticker}: {e}")
        df = pd.DataFrame()
    finally:
        con.close()
    return df

def calculate_indicators(df):
    if df.empty: return df
    # Calculate RSI on the Close column using the Faster Period
    df['rsi'] = ta.rsi(df['close'], length=VIX_RSI_PERIOD)
    return df

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def scan_and_generate_manifest():
    log.info(f"📡 Scanning Intraday Data (Active Mode: RSI({VIX_RSI_PERIOD}) < {VIX_RSI_THRESHOLD})...")
    
    # 1. Fetch Data
    df_spx = fetch_intraday_data("SPX")
    df_vix = fetch_intraday_data("VIX")
    
    if df_spx.empty or df_vix.empty:
        log.error("❌ Missing Data. Run 'ingest_indices.py' first.")
        return

    # 2. Prep Indicators
    df_vix = calculate_indicators(df_vix)
    
    # Merge VIX and SPX (Backfill SPX price to VIX timestamp)
    df_merged = pd.merge_asof(
        df_vix.sort_values('datetime_utc'), 
        df_spx[['datetime_utc', 'close']].rename(columns={'close': 'spx_close'}).sort_values('datetime_utc'),
        on='datetime_utc',
        direction='backward'
    )
    
    # 3. Calendar Audit
    min_date = df_merged['datetime_utc'].min().date()
    max_date = df_merged['datetime_utc'].max().date()
    expected_days = get_market_calendar(min_date, max_date)
    
    df_merged['date'] = df_merged['datetime_utc'].dt.date
    daily_groups = df_merged.groupby('date')
    
    signals = []
    last_signal_times = {} 
    
    print(f"\n{'DATE':<12} | {'STATUS':<15} | {'MIN RSI':<8} | {'NOTES'}")
    print("-" * 60)

    # Iterate through EXPECTED trading days to spot gaps
    for trade_date in expected_days:
        if trade_date not in daily_groups.groups:
            print(f"{str(trade_date):<12} | ⚠️ MISSING DATA  | {'--':<8} | Run Ingestion")
            continue
            
        # Get data for this day
        day_data = daily_groups.get_group(trade_date)
        min_rsi = day_data['rsi'].min()
        
        # Check for Signals
        day_signals = day_data[day_data['rsi'] < VIX_RSI_THRESHOLD]
        
        status = "NO SIGNAL"
        note = ""
        
        if not day_signals.empty:
            status = "✅ SIGNAL"
            # Process signals with cooldown
            for i, row in day_signals.iterrows():
                entry_time = row['datetime_utc']
                last_time = last_signal_times.get(trade_date)
                
                if last_time:
                    delta = (entry_time - last_time).total_seconds() / 60
                    if delta < COOLDOWN_MINUTES:
                        continue 

                xsp_est = row['spx_close'] / 10.0
                signals.append({
                    'date': trade_date,
                    'entry_timestamp_utc': int(entry_time.timestamp() * 1000),
                    'signal_type': 'VIX_RSI_LONG',
                    'xsp_price': xsp_est,
                    'meta_data': f"VIX_RSI({VIX_RSI_PERIOD}):{row['rsi']:.2f}"
                })
                last_signal_times[trade_date] = entry_time
            
            note = f"Found {len(day_signals)} ticks < {VIX_RSI_THRESHOLD}"
        else:
            # Observability: Why no signal?
            note = f"Low Volatility (RSI > {VIX_RSI_THRESHOLD})"

        print(f"{str(trade_date):<12} | {status:<15} | {min_rsi:>6.2f}   | {note}")

    print("-" * 60)

    # Write to Manifest (Always Wipe & Rebuild to reflect new logic)
    con = duckdb.connect(str(config.DB_FILE))
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
    
    if signals:
        con.execute(f"""
            CREATE TABLE {config.TBL_MANIFEST} (
                date DATE,
                entry_timestamp_utc BIGINT,
                signal_type VARCHAR,
                xsp_price DOUBLE,
                meta_data VARCHAR
            )
        """)
        signals_df = pd.DataFrame(signals)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM signals_df")
        log.info(f"💾 Manifest Updated: {len(signals)} Signals (Active Mode).")
    else:
        log.info("⚠️ No signals generated with current settings.")
        
    con.close()

if __name__ == "__main__":
    scan_and_generate_manifest()