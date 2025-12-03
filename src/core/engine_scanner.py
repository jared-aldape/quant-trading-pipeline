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
from src.core import strat_fractal

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

# ==============================================================================
# 4. SCANNER LOGIC (FRACTAL FLOW)
# ==============================================================================
def scan_and_generate_manifest():
    log.info("📡 Scanning for VIX Fractal Flow (Strategy Module)...")
    
    # 1. Fetch Data
    spx_df = fetch_intraday_data('SPX') # For RTH logic & Price Reference
    vix_df = fetch_intraday_data('VIX') # For Signals
    
    if spx_df.empty or vix_df.empty:
        log.error("❌ Missing SPX or VIX data. Aborting scan.")
        return

    # 2. Calculate Indicators (Centralized in strat_fractal)
    log.info("📊 Calculating Indicators via strat_fractal...")
    vix_1h_df = strat_fractal.calculate_macd(vix_df.resample('1h').last().dropna())
    vix_5m_df = strat_fractal.calculate_macd(vix_df.resample('5min').last().dropna())
    vix_1m_data = vix_df # Use raw 1m for check reference

    # 3. Scan Loop (Day by Day)
    signals = []
    days = spx_df['datetime_et'].dt.date.unique()
    last_signal_times = {} # Track last signal per day for Cooldown

    print("\nDATE         | STATUS          | TRIGGERS   | NOTES")
    print("-" * 70)

    for date in days:
        day_str = str(date)
        
        # Define RTH Window for this specific day
        day_open_et = config.TZ_NY.localize(datetime.combine(date, OPEN_TIME_ET))
        day_close_et = config.TZ_NY.localize(datetime.combine(date, CLOSE_TIME_ET))
        
        # Hard Deck: 09:45 ET (15 mins after open)
        hard_deck_time = day_open_et + timedelta(minutes=15)
        
        # Get 1m bars for this trading day (RTH Only)
        daily_bars = vix_1m_data[
            (vix_1m_data['datetime_et'] >= day_open_et) & 
            (vix_1m_data['datetime_et'] <= day_close_et)
        ]
        
        count = 0
        status = "NO SIGNAL"

        for ts_current in daily_bars.index:
            
            # Check Hard Deck Law
            is_past_hard_deck = ts_current >= hard_deck_time
            
            # Check Cooldown (One signal per hour max)
            last_ts = last_signal_times.get(date)
            is_cooldown_active = False
            if last_ts:
                time_since_last = (ts_current - last_ts).total_seconds() / 60
                if time_since_last < COOLDOWN_MINUTES:
                    is_cooldown_active = True

            # Check Fractal Signal
            decision = strat_fractal.check_fractal_flow(vix_1h_df, vix_5m_df, ts_current)
            
            if decision['signal'] and is_past_hard_deck and not is_cooldown_active:
                
                # --- BUG FIX: CORRECT XSP ESTIMATION ---
                # 1. Lookup SPX Price at this timestamp
                try:
                    # 'asof' finds the last valid price at or before ts_current
                    spx_price = spx_df['close'].asof(ts_current)
                    
                    # 2. APPLY SCALING LAW (The Fix)
                    # XSP = SPX / 10
                    xsp_est = spx_price / 10.0
                    
                except Exception:
                    xsp_est = 0.0
                    log.warning(f"⚠️ SPX Price Lookup Failed for {ts_current}")
                # ---------------------------------------

                if xsp_est > 0: # Only proceed if we have a valid price
                    timestamp_ms = int(ts_current.timestamp() * 1000)

                    # --- Enforcing Straddle-Bias Protocol (75% Call / 25% Put) ---
                    
                    # 1. Long Call Component (Primary Trade: 75% Bias)
                    signals.append({
                        'date': date,
                        'entry_timestamp_utc': timestamp_ms,
                        'signal_type': 'VIX_FRACTAL_LONG',
                        'xsp_price': xsp_est, 
                        'trade_type': 'call',
                        'meta_data': decision['reason'] + " | Bias: 75%",
                        'allocation_pct': 0.75 
                    })
                    
                    # 2. Long Put Component (Hedge/Straddle-Bias: 25% Bias)
                    signals.append({
                        'date': date,
                        'entry_timestamp_utc': timestamp_ms + 1, # PK offset
                        'signal_type': 'VIX_FRACTAL_LONG',
                        'xsp_price': xsp_est,
                        'trade_type': 'put',
                        'meta_data': decision['reason'] + " | Bias: 25%",
                        'allocation_pct': 0.25 
                    })
                    
                    last_signal_times[date] = ts_current
                    count += 2 
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
                meta_data VARCHAR,
                allocation_pct DOUBLE
            )
        """)
        signals_df = pd.DataFrame(signals)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM signals_df")
        log.info(f"💾 Manifest Rebuilt: {len(signals_df)} Fractal Signals (RTH Only).")
    else:
        con.execute(f"""
            CREATE TABLE {config.TBL_MANIFEST} (
                entry_timestamp_utc BIGINT, date DATE, signal_type VARCHAR, 
                xsp_price DOUBLE, trade_type VARCHAR, meta_data VARCHAR, allocation_pct DOUBLE
            )
        """)
        log.info("💾 Manifest Rebuilt: 0 Signals.")
    
    con.close()

if __name__ == '__main__':
    scan_and_generate_manifest()