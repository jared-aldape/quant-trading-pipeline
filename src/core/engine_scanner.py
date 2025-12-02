import sys
import duckdb
import pandas as pd
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
from src.core import strat_fractal  # <--- NEW CENTRALIZED LOGIC

log = get_logger("SignalScanner")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
COOLDOWN_MINUTES = 60
OPEN_TIME_ET = time(9, 30)
CLOSE_TIME_ET = time(16, 0)

# ==============================================================================
# 3. DATA FETCHING
# ==============================================================================
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

# ==============================================================================
# 4. CORE SCANNER LOGIC
# ==============================================================================
def scan_and_generate_manifest():
    log.info("📡 Scanning for VIX Fractal Flow (Strategy Module)...")
    
    # 1. Load Data
    df_spx = fetch_intraday_data("SPX")
    df_vix = fetch_intraday_data("VIX")
    
    if df_spx.empty or df_vix.empty:
        log.error("❌ Missing Data.")
        return

    # 2. Prepare Indicators (Using Centralized Logic)
    # We pass the raw DF to the strategy calculator
    # Rename columns to match what strat_fractal expects if needed, 
    # but our fetcher returns standard names (close, open, etc.)
    
    log.info("📊 Calculating Indicators via strat_fractal...")
    
    # 5m Calculation
    vix_5m = df_vix.copy().set_index('datetime_utc').sort_index()
    vix_5m = strat_fractal.calculate_macd(vix_5m)
    
    # 1H Calculation (Resample first)
    vix_1h = vix_5m.resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    vix_1h = strat_fractal.calculate_macd(vix_1h)
    
    # 3. Merge for Iteration (Align SPX price to VIX time)
    # We need to iterate 5m bars to find the crossover moment
    df_merged = pd.merge_asof(
        vix_5m.reset_index(),
        df_spx[['datetime_utc', 'close']].rename(columns={'close': 'spx_close'}).sort_values('datetime_utc'),
        on='datetime_utc',
        direction='backward'
    )
    
    # 4. Scan Loop
    signals = []
    last_signal_times = {}
    tz_ny = pytz.timezone('America/New_York')
    
    # We iterate day by day to respect RTH easily
    df_merged['date'] = df_merged['datetime_utc'].dt.date
    
    print(f"\n{'DATE':<12} | {'STATUS':<15} | {'TRIGGERS':<10} | {'NOTES'}")
    print("-" * 70)
    
    for date, day_data in df_merged.groupby('date'):
        day_data = day_data.sort_values('datetime_utc')
        count = 0
        status = "NO SIGNAL"
        
        # We need a rolling window or lookback for the crossover check.
        # The Strategy Module expects full DFs or specific rows.
        # To make this efficient, we can pre-calculate the logic vectors here 
        # OR just call the check function iteratively. 
        # Vectorized is faster, but the Strategy function `check_fractal_setup` 
        # is designed for robustness (checking lengths, etc). 
        # Let's do a hybrid: Calculate the "River" (1H) state for the whole day, then check "Ripple" (5m).
        
        # A. Align 1H Macro State to 5m bars
        # This gives us the 'hist' of the 1H bar that *contains* or *precedes* the 5m bar
        day_vix_1h = vix_1h[vix_1h.index.date == date]
        if day_vix_1h.empty: continue
        
        # B. Iterate 5m bars
        for i in range(1, len(day_data)):
            curr_row = day_data.iloc[i]
            prev_row = day_data.iloc[i-1]
            
            ts_current = curr_row['datetime_utc']
            
            # --- RTH CHECK ---
            ts_ny = ts_current.tz_convert(tz_ny).time()
            if not (OPEN_TIME_ET <= ts_ny <= CLOSE_TIME_ET):
                continue
                
            # --- COOLDOWN CHECK ---
            last_time = last_signal_times.get(date)
            if last_time:
                delta = (ts_current - last_time).total_seconds() / 60
                if delta < COOLDOWN_MINUTES: continue

            # --- STRATEGY CHECK ---
            # 1. Macro Condition (River)
            # Find the relevant 1H bar (AsOf)
            # We use the index of day_vix_1h to find the latest closed bar
            macro_slice = day_vix_1h[day_vix_1h.index <= ts_current]
            if macro_slice.empty: continue
            
            # 2. Micro Condition (Ripple)
            # We create a mini-df of 2 rows to pass to the strategy checker
            micro_mini = pd.DataFrame([prev_row, curr_row])
            
            # CALL THE BRAIN
            # We construct a dummy 1H frame with the current macro state
            # This is slightly inefficient but ensures strict logic adherence
            current_macro_state = macro_slice.iloc[[-1]] 
            
            decision = strat_fractal.check_fractal_setup(current_macro_state, micro_mini)
            
            if decision['signal']:
                # Valid Signal Found
                xsp_est = curr_row['spx_close'] / 10.0
                
                signals.append({
                    'date': date,
                    'entry_timestamp_utc': int(ts_current.timestamp() * 1000),
                    'signal_type': 'VIX_FRACTAL_LONG',
                    'xsp_price': xsp_est,
                    'trade_type': 'call',
                    'meta_data': decision['reason']
                })
                
                last_signal_times[date] = ts_current
                count += 1
                status = "✅ FRACTAL"
        
        note = f"{count} RTH entries" if count > 0 else "No RTH alignment"
        print(f"{str(date):<12} | {status:<15} | {count:<10} | {note}")

    print("-" * 70)

    # 5. Save to DB
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