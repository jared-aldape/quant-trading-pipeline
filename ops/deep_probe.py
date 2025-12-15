import sys
import duckdb
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE SETUP
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    print(f"✅ Configuration Loaded. Target DB: {config.DB_FILE}")
except ImportError:
    print("❌ CRITICAL: Run from Project Root.")
    sys.exit(1)

def run_probe():
    print("\n⚔️  QUANT OS v3.3: DEEP PROBE DIAGNOSTIC")
    print("========================================")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # ---------------------------------------------------------
    # STEP 1: CAPTURE A FAILED MACRO SIGNAL
    # ---------------------------------------------------------
    print("\n🔍 [1] HUNTING FOR FAILED MACRO SIGNAL...")
    # We look for a signal in early 2025 (e.g., April) which we know didn't trade
    sig = con.execute("""
        SELECT * FROM trade_manifest 
        WHERE signal_type LIKE 'MACRO%' 
        AND date BETWEEN '2025-03-01' AND '2025-06-01'
        LIMIT 1
    """).df()
    
    if sig.empty:
        print("❌ No Macro Signals found in Q2 2025. (Did you run the scanner?)")
        return

    # Extract Target Intel
    target_date = pd.to_datetime(sig.iloc[0]['date'])
    target_ts = pd.to_datetime(sig.iloc[0]['entry_timestamp_utc'], unit='ms')
    target_price = sig.iloc[0]['xsp_price']
    trade_type = sig.iloc[0]['trade_type']
    
    print(f"   🎯 TARGET ACQUIRED:")
    print(f"      Signal Date:   {target_date.date()}")
    print(f"      Entry Attempt: {target_ts} (UTC)")
    print(f"      Underlying:    ${target_price:.2f}")
    print(f"      Trade Type:    {trade_type.upper()}")
    print(f"      Ideal Strike:  ${target_price * 0.98:.2f} - ${target_price * 1.02:.2f} (+/- 2%)")

    # ---------------------------------------------------------
    # STEP 2: SCAN THE VAULT FOR THAT DAY
    # ---------------------------------------------------------
    print("\n🔎 [2] SCANNING VAULT FOR MATCHING ASSETS...")
    
    # We look for ANY options for that day
    day_start = target_ts.strftime('%Y-%m-%d')
    
    # Check Time Distribution first
    print(f"      Querying options for date: {day_start}...")
    
    vault_dump = con.execute(f"""
        SELECT ticker, datetime_utc, open, strike, type
        FROM options_1m 
        WHERE CAST(datetime_utc AS DATE) = '{day_start}'
        LIMIT 20
    """).df()
    
    if vault_dump.empty:
        print("   ❌ CRITICAL FAILURE: No options found for this specific date.")
        print("      -> The Integrity Check showed data for the *Month*, but this *Day* is empty.")
        
        # Check neighbors
        print("      -> Checking neighbor days...")
        neighbor_check = con.execute(f"""
            SELECT CAST(datetime_utc AS DATE) as d, COUNT(*) 
            FROM options_1m 
            WHERE datetime_utc BETWEEN '{day_start}'::TIMESTAMP - INTERVAL '5 days' 
                                   AND '{day_start}'::TIMESTAMP + INTERVAL '5 days'
            GROUP BY 1 ORDER BY 1
        """).df()
        print(neighbor_check)
        return

    # ---------------------------------------------------------
    # STEP 3: ANALYZE THE AVAILABLE INVENTORY
    # ---------------------------------------------------------
    print(f"   ✅ Found Inventory ({len(vault_dump)}+ rows). analyzing sample:")
    print(vault_dump.head(5))
    
    # Check Strike Alignment
    print("\n   [Strike Analysis]")
    strikes = con.execute(f"""
        SELECT MIN(strike) as min_k, MAX(strike) as max_k, COUNT(DISTINCT strike) as k_count
        FROM options_1m 
        WHERE CAST(datetime_utc AS DATE) = '{day_start}'
    """).df()
    print(f"      Available Strikes: {strikes.iloc[0]['min_k']} to {strikes.iloc[0]['max_k']}")
    
    # Check Price Availability
    print("\n   [Price Analysis]")
    prices = con.execute(f"""
        SELECT COUNT(*) as total, COUNT(open) as has_open, COUNT(*) FILTER (WHERE open > 0) as valid_open
        FROM options_1m 
        WHERE CAST(datetime_utc AS DATE) = '{day_start}'
    """).df()
    print(f"      Total Rows: {prices.iloc[0]['total']}")
    print(f"      Rows with Open > 0: {prices.iloc[0]['valid_open']}")
    
    if prices.iloc[0]['valid_open'] == 0:
        print("   ⚠️  SMOKING GUN: All prices are 0.0 or NULL!")
        print("       -> The Backtester rejects trades with no price.")

    con.close()

if __name__ == "__main__":
    run_probe()