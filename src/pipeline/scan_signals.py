import sys
import duckdb
import pandas as pd
import pandas_ta as ta
import numpy as np
from pathlib import Path
from datetime import datetime, time, timedelta
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SignalScanner")

# ==============================================================================
# 2. CONFIGURATION (FRACTAL FLOW MODE)
# ==============================================================================
COOLDOWN_MINUTES = 60

# --- RTH WALLS (New) ---
# We use Eastern Time to align with Market Rules
OPEN_TIME_ET = time(9, 30)
CLOSE_TIME_ET = time(16, 0)

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def get_market_calendar(start_date, end_date):
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return pd.date_range(start=start_date, end=end_date, freq=us_bd).date

def fetch_intraday_data(ticker):
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    query = f"""
        SELECT datetime_utc, close, open, high, low
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

def calculate_fractal_flow(df_vix):
    if df_vix.empty: return pd.DataFrame()
    
    # --- 1. MICRO (5m) ---
    vix_5m = df_vix.copy().set_index('datetime_utc')
    macd_5m = ta.macd(vix_5m['close'], fast=12, slow=26, signal=9)
    vix_5m = pd.concat([vix_5m, macd_5m], axis=1)
    
    vix_5m.rename(columns={
        'MACD_12_26_9': 'micro_line',
        'MACDs_12_26_9': 'micro_signal'
    }, inplace=True)

    # --- 2. MACRO (1H) ---
    vix_1h = vix_5m.resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    
    macd_1h = ta.macd(vix_1h['close'], fast=12, slow=26, signal=9)
    vix_1h = pd.concat([vix_1h, macd_1h], axis=1)
    vix_1h.rename(columns={'MACDh_12_26_9': 'macro_hist'}, inplace=True)
    
    # --- 3. MERGE ---
    vix_final = pd.merge_asof(
        vix_5m.sort_index(),
        vix_1h[['macro_hist']].sort_index(),
        left_index=True,
        right_index=True,
        direction='backward'
    )
    
    return vix_final

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def scan_and_generate_manifest():
    log.info("📡 Scanning for VIX Fractal Flow (RTH ONLY)...")
    
    df_spx = fetch_intraday_data("SPX")
    df_vix = fetch_intraday_data("VIX")
    
    if df_spx.empty or df_vix.empty:
        log.error("❌ Missing Data.")
        return

    df_flow = calculate_fractal_flow(df_vix)
    
    df_merged = pd.merge_asof(
        df_flow, 
        df_spx[['datetime_utc', 'close']].rename(columns={'close': 'spx_close'}).set_index('datetime_utc').sort_index(),
        left_index=True,
        right_index=True,
        direction='backward'
    ).reset_index()
    
    signals = []
    last_signal_times = {}
    
    df_merged['date'] = df_merged['datetime_utc'].dt.date
    daily_groups = df_merged.groupby('date')
    
    # Define Timezone Objects
    tz_ny = pytz.timezone('America/New_York')
    
    print(f"\n{'DATE':<12} | {'STATUS':<15} | {'TRIGGERS':<10} | {'NOTES'}")
    print("-" * 70)
    
    for date, day_data in daily_groups:
        day_data = day_data.sort_values('datetime_utc')
        
        # --- THE SIGNAL LOGIC ---
        macro_bearish = day_data['macro_hist'] < 0
        
        day_data['prev_line'] = day_data['micro_line'].shift(1)
        day_data['prev_sig'] = day_data['micro_signal'].shift(1)
        
        cross_down = (day_data['micro_line'] < day_data['micro_signal']) & \
                     (day_data['prev_line'] > day_data['prev_sig'])
                     
        valid_signals = day_data[cross_down & macro_bearish]
        
        status = "NO SIGNAL"
        count = 0
        
        if not valid_signals.empty:
            for _, row in valid_signals.iterrows():
                entry_time_utc = row['datetime_utc']
                
                # --- RTH CHECK (NEW) ---
                # Convert UTC entry time to NY Time
                entry_time_ny = entry_time_utc.tz_convert(tz_ny).time()
                
                # Filter: Is this signal inside 9:30 AM - 4:00 PM ET?
                if not (OPEN_TIME_ET <= entry_time_ny <= CLOSE_TIME_ET):
                    continue # Skip pre-market/after-hours signals
                
                # Cooldown Check
                last_time = last_signal_times.get(date)
                if last_time:
                    delta = (entry_time_utc - last_time).total_seconds() / 60
                    if delta < COOLDOWN_MINUTES:
                        continue
                
                xsp_est = row['spx_close'] / 10.0
                
                signals.append({
                    'date': date,
                    'entry_timestamp_utc': int(entry_time_utc.timestamp() * 1000),
                    'signal_type': 'VIX_FRACTAL_LONG',
                    'xsp_price': xsp_est,
                    'trade_type': 'call',
                    'meta_data': f"Macro:{row['macro_hist']:.2f}|MicroCross"
                })
                last_signal_times[date] = entry_time_utc
                count += 1
                status = "✅ FRACTAL"
        
        note = f"{count} RTH entries" if count > 0 else "No RTH alignment"
        print(f"{str(date):<12} | {status:<15} | {count:<10} | {note}")

    print("-" * 70)

    con = duckdb.connect(str(config.DB_FILE))
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
    
    if signals:
        con.execute(f"""
            CREATE TABLE {config.TBL_MANIFEST} (
                date DATE,
                entry_timestamp_utc BIGINT,
                signal_type VARCHAR,
                xsp_price DOUBLE,
                trade_type VARCHAR,
                meta_data VARCHAR
            )
        """)
        signals_df = pd.DataFrame(signals)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM signals_df")
        log.info(f"💾 Manifest Rebuilt: {len(signals)} Fractal Signals (RTH Only).")
    else:
        log.info("⚠️ No signals found in RTH.")
        
    con.close()

if __name__ == "__main__":
    scan_and_generate_manifest()