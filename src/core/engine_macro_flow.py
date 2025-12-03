import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
import pytz
from datetime import time

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: src/core/engine_macro_flow.py
# Root: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("MacroFlowEngine")

# ==============================================================================
# 2. CONFIGURATION & CONSTANTS
# ==============================================================================
FLOW_LOOKBACK_DAYS = 20  # Rolling 20-day window (~1 trading month)
FLOW_BIAS_THRESHOLD = 55.0  # Conviction threshold (>55% to set bias)
TZ_NY = pytz.timezone('America/New_York')

# RTH Times (9:30 AM ET to 4:00 PM ET)
OPEN_TIME_ET = time(9, 30)
CLOSE_TIME_ET = time(16, 0)

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================

def get_daily_rth_flow(day_group):
    """
    Extracts the RTH Open (09:30 ET) and RTH Close (16:00 ET) 
    for a single trading day group.
    """
    # Convert UTC timestamps to NY time for filtering
    day_group['datetime_ny'] = day_group['datetime_utc'].dt.tz_convert(TZ_NY)
    
    # Filter for Regular Trading Hours
    rth_data = day_group[
        (day_group['datetime_ny'].dt.time >= OPEN_TIME_ET) & 
        (day_group['datetime_ny'].dt.time <= CLOSE_TIME_ET)
    ]
    
    if rth_data.empty:
        return pd.Series({'Open': None, 'Close': None})
    
    # RTH Open: Price of the first bar at or after 09:30 ET
    rth_open = rth_data.iloc[0]['open']
    
    # RTH Close: Price of the last bar at or before 16:00 ET
    rth_close = rth_data.iloc[-1]['close']
    
    return pd.Series({'Open': rth_open, 'Close': rth_close})

def run_pipeline():
    """
    Main Execution Pipeline:
    1. Fetch SPX minute data.
    2. Aggregate to Daily RTH Open/Close.
    3. Calculate Rolling 20-Day Bull/Bear Bias.
    4. Save State to 'macro_flow_state' table.
    """
    log.info("🌊 Starting Macro Flow Analysis...")
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Fetch ALL SPX Data from Vault
    query = f"""
        SELECT datetime_utc, open, close
        FROM {config.TBL_INDICES} 
        WHERE ticker = 'SPX' 
        ORDER BY datetime_utc ASC
    """
    try:
        df = con.execute(query).df()
    except Exception as e:
        log.error(f"❌ Failed to fetch SPX data for Macro Flow analysis: {e}")
        con.close()
        return

    if df.empty:
        log.warning("⚠️ SPX data is empty. Macro Flow Analysis skipped.")
        con.close()
        return

    # Ensure UTC timezone awareness
    df['datetime_utc'] = pd.to_datetime(df['datetime_utc']).dt.tz_localize(pytz.utc)
    
    # 2. Calculate Daily RTH Open/Close
    # Group by NY Date to handle session boundaries correctly
    log.info(f"📊 Processing {len(df)} minute bars...")
    daily_summary = df.groupby(df['datetime_utc'].dt.tz_convert(TZ_NY).dt.date).apply(get_daily_rth_flow)
    
    # --- FIX START: Robust Index Handling ---
    daily_summary.index.name = 'date' # Explicitly name the index
    daily_summary = daily_summary.dropna(subset=['Open', 'Close']).reset_index()
    # Now 'date' is guaranteed to be a column
    # --- FIX END ---

    if daily_summary.empty:
        log.warning("⚠️ No valid RTH days found. Macro Flow Analysis skipped.")
        con.close()
        return

    # 3. Determine Daily Direction (1 = BULL, -1 = BEAR, 0 = FLAT)
    daily_summary['Direction'] = np.where(daily_summary['Close'] > daily_summary['Open'], 1, 
                                        np.where(daily_summary['Close'] < daily_summary['Open'], -1, 0))

    # 4. Calculate Rolling Bull/Bear Percentage (Lookback = 20 days)
    daily_summary['Rolling_Bull_Count'] = daily_summary['Direction'].rolling(window=FLOW_LOOKBACK_DAYS).apply(
        lambda x: (x > 0).sum(), raw=True)
        
    daily_summary['Rolling_Total_Days'] = daily_summary['Direction'].rolling(window=FLOW_LOOKBACK_DAYS).count()
    
    # Calculate Percentages
    daily_summary['bull_pct'] = (daily_summary['Rolling_Bull_Count'] / daily_summary['Rolling_Total_Days']) * 100
    daily_summary['bear_pct'] = 100 - daily_summary['bull_pct'] 
    
    # 5. Determine Flow Bias
    daily_summary['flow_bias'] = np.where(daily_summary['bull_pct'] >= FLOW_BIAS_THRESHOLD, 'BULL', 
                                         np.where(daily_summary['bear_pct'] >= FLOW_BIAS_THRESHOLD, 'BEAR', 'NEUTRAL'))
    
    # 6. Prepare Final DataFrame for Vault
    final_df = daily_summary[['date', 'flow_bias', 'bull_pct', 'bear_pct']].dropna()
    final_df['date'] = pd.to_datetime(final_df['date']).dt.date
    
    log.info(f"💾 Calculated Macro Flow State for {len(final_df)} trading days.")
    
    # 7. Save to DB
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MACRO_FLOW}")
    con.execute(f"""
        CREATE TABLE {config.TBL_MACRO_FLOW} (
            date DATE NOT NULL,
            flow_bias VARCHAR,
            bull_pct DOUBLE,
            bear_pct DOUBLE,
            PRIMARY KEY (date)
        )
    """)
    con.register('macro_flow_source', final_df)
    con.execute(f"INSERT INTO {config.TBL_MACRO_FLOW} SELECT * FROM macro_flow_source")
    
    log.info(f"✅ Macro Flow State saved to Vault ({config.TBL_MACRO_FLOW}).")
    con.close()

if __name__ == '__main__':
    run_pipeline()