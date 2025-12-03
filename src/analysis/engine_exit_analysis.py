import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, time, timedelta
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: src/analysis/engine_exit_analysis.py
# Root: .../QUANT-OS/
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("ExitAnalysis")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
# Window Definitions (New York Time)
# Morning: Open to 12:30 PM ET (09:30 PST)
# Afternoon: 12:30 PM ET to Close
MORNING_CUTOFF_ET = time(12, 30) 

# ==============================================================================
# 3. HELPER: TICKER RECONSTRUCTION
# ==============================================================================
def reconstruct_ticker(row):
    """
    Re-derives the Option Ticker used for a specific signal 
    so we can look up its price history in options_1m.
    """
    try:
        # 1. Parse Date
        date_obj = row['date'] # datetime.date
        date_str = date_obj.strftime('%y%m%d')
        
        # 2. Parse Type
        opt_type = 'C' if row['trade_type'] == 'call' else 'P'
        
        # 3. Parse Strike (From stored xsp_price in manifest)
        # Note: Ingestion used Round(Price) * 1000
        # We assume xsp_price in manifest is the SCALED price (e.g. 650.00)
        strike_raw = round(row['xsp_price'])
        strike_str = f"{int(strike_raw * 1000):08d}"
        
        # 4. Construct Ticker
        # Format: O:XSP{YYMMDD}{C/P}{STRIKE}
        return f"O:XSP{date_str}{opt_type}{strike_str}"
        
    except Exception as e:
        return None

# ==============================================================================
# 4. FORENSIC CORE
# ==============================================================================
def run_forensic_lab():
    log.info("🕵️ STARTING FORENSIC LAB: Time-to-Max-Gain Analysis")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. Fetch Manifest (The Signals)
    # We only care about entries that successfully generated a trade
    try:
        manifest_df = con.execute(f"""
            SELECT * FROM {config.TBL_MANIFEST}
            ORDER BY entry_timestamp_utc ASC
        """).df()
    except Exception:
        log.error("❌ Manifest table not found. Run pipeline first.")
        return

    if manifest_df.empty:
        log.warning("⚠️ Manifest is empty. Nothing to analyze.")
        return

    stats = []

    # 2. Iterate Every Signal
    log.info(f"🔬 Analyzing {len(manifest_df)} signals for optimal exit timing...")
    
    for _, row in manifest_df.iterrows():
        # A. Reconstruct Ticker
        ticker = reconstruct_ticker(row)
        if not ticker: continue
        
        # B. Define Time Window
        # Entry time is in UTC ms
        entry_ts = pd.Timestamp(row['entry_timestamp_utc'], unit='ms', tz='UTC')
        entry_ts_ny = entry_ts.tz_convert(config.TZ_NY)
        
        # End of Day (Hard Stop)
        eod_ts = entry_ts.ceil('D') # Approximate, we just filter > entry
        
        # C. Fetch Option Price History (The Truth)
        # We want all 1m bars for this option AFTER the entry time
        query = f"""
            SELECT datetime_utc, high, open
            FROM {config.TBL_OPTIONS}
            WHERE ticker = '{ticker}'
            AND datetime_utc >= '{entry_ts.strftime('%Y-%m-%d %H:%M:%S')}'
            ORDER BY datetime_utc ASC
        """
        price_df = con.execute(query).df()
        
        if price_df.empty:
            continue
            
        # Ensure TZ awareness
        price_df['datetime_utc'] = pd.to_datetime(price_df['datetime_utc']).dt.tz_localize('UTC')
        
        # D. Find Max Gain
        # Entry Price = Open of the first bar (approx execution)
        entry_price = price_df.iloc[0]['open']
        if entry_price <= 0: continue
            
        # Find the highest High in the dataframe
        max_price_idx = price_df['high'].idxmax()
        max_price = price_df.loc[max_price_idx, 'high']
        max_ts = price_df.loc[max_price_idx, 'datetime_utc']
        
        # E. Calculate Metrics
        max_gain_pct = (max_price - entry_price) / entry_price
        time_to_max_gain_min = (max_ts - entry_ts).total_seconds() / 60
        
        # F. Classify Window (Morning vs Afternoon)
        is_morning = entry_ts_ny.time() < MORNING_CUTOFF_ET
        window_label = "MORNING (09:30-12:30 ET)" if is_morning else "AFTERNOON (12:30-16:00 ET)"
        
        stats.append({
            'date': row['date'],
            'type': row['trade_type'],
            'window': window_label,
            'entry_price': entry_price,
            'max_price': max_price,
            'max_gain_pct': max_gain_pct * 100,
            'minutes_to_peak': time_to_max_gain_min
        })

    con.close()
    
    # ==============================================================================
    # 5. GENERATE REPORT
    # ==============================================================================
    if not stats:
        log.warning("⚠️ No valid price data found for signals. (Ingest Options might be incomplete).")
        return

    results = pd.DataFrame(stats)
    
    print("\n" + "="*80)
    print("🧠 FORENSIC LAB RESULTS: OPTIMAL EXIT TIMING")
    print("="*80)
    
    # Group by Window to see the difference
    summary = results.groupby('window')[['max_gain_pct', 'minutes_to_peak']].describe()
    
    # Formatting for readability
    print("\n--- 1. STATS BY TRADING WINDOW ---")
    
    for window in results['window'].unique():
        subset = results[results['window'] == window]
        print(f"\n📂 {window}:")
        print(f"   Signals Analyzed: {len(subset)}")
        print(f"   Avg Max Potential: {subset['max_gain_pct'].mean():.2f}%")
        print(f"   Avg Time to Peak:  {subset['minutes_to_peak'].mean():.1f} min")
        print(f"   Median Time to Peak: {subset['minutes_to_peak'].median():.1f} min")
        print(f"   ⚡ 80% of gains occur within: {subset['minutes_to_peak'].quantile(0.8):.1f} min")

    print("\n" + "="*80)
    print("💡 STRATEGIC RECOMMENDATION")
    
    # Automated Insight
    morning_time = results[results['window'].str.contains("MORNING")]['minutes_to_peak'].median()
    afternoon_time = results[results['window'].str.contains("AFTERNOON")]['minutes_to_peak'].median()
    
    if pd.isna(morning_time): morning_time = 0
    if pd.isna(afternoon_time): afternoon_time = 0

    print(f"Based on this data, your 'Time-Based Exit' settings should be:")
    print(f"   • Morning Trades:  Check exit after ~{int(morning_time)} minutes.")
    print(f"   • Afternoon Trades: Check exit after ~{int(afternoon_time)} minutes.")
    print("="*80 + "\n")

if __name__ == '__main__':
    run_forensic_lab()