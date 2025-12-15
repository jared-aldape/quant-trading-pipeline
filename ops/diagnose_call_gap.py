import sys
import duckdb
import pandas as pd
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def diagnose():
    print(f"🕵️ CALL OPTION FORENSICS: {config.DB_FILE}\n")
    
    if not config.DB_FILE.exists():
        print("❌ Database not found.")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)

    # 1. CHECK THE MANIFEST (Intent)
    print("--- 1. MANIFEST INSPECTION ---")
    try:
        dist = con.execute(f"""
            SELECT 
                upper(trade_type) as type, 
                COUNT(*) as count, 
                MIN(date) as first_sig, 
                MAX(date) as last_sig
            FROM {config.TBL_MANIFEST}
            GROUP BY 1
        """).df()
        print(dist)
        
        if 'CALL' not in dist['type'].values:
            print("\n🚨 CRITICAL FINDING: No 'CALL' signals exist in the Manifest.")
            print("   -> The Scanner simply never signaled a buy.")
            print("   -> Solution: Adjust Scanner thresholds or check logic.")
            con.close()
            return
    except Exception as e:
        print(f"❌ Manifest Error: {e}")
        return

    # 2. CHECK THE DATA (Fuel)
    print("\n--- 2. BULK DATA INSPECTION ---")
    try:
        # Check for ANY Call tickers
        call_sample = con.execute(f"""
            SELECT count(*) as call_rows 
            FROM {config.TBL_OPTIONS} 
            WHERE ticker LIKE '%C00%'
        """).fetchone()
        print(f"Total Call Option Rows in DB: {call_sample[0]:,}")
        
        if call_sample[0] == 0:
            print("🚨 CRITICAL FINDING: No Call Option data found in DB.")
            print("   -> Ingest Bulk History only downloaded Puts?")
            con.close()
            return
    except Exception as e:
        print(f"❌ Data Error: {e}")

    # 3. CHECK THE LINK (Match)
    print("\n--- 3. MATCHING TEST (First 5 Calls) ---")
    calls = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE upper(trade_type) LIKE '%CALL%' LIMIT 5").df()
    
    for i, row in calls.iterrows():
        # Reconstruct Ticker logic from Engine
        date_str = pd.to_datetime(row['date']).strftime('%Y-%m-%d')
        date_fmt = pd.to_datetime(row['date']).strftime('%y%m%d')
        strike = int(row['xsp_price'])
        ticker = f"O:XSP{date_fmt}C{strike * 1000:08d}"
        
        print(f"🔎 Signal: {date_str} | Target Strike: {strike} | Looking for: {ticker}")
        
        # Check DB
        exists = con.execute(f"SELECT count(*) FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}'").fetchone()[0]
        
        if exists > 0:
            print(f"   ✅ FOUND: {exists} rows.")
        else:
            print(f"   ❌ MISSING: Ticker not found.")
            # Check neighbors
            print("      Checking neighbors...")
            neighbors = con.execute(f"""
                SELECT DISTINCT ticker FROM {config.TBL_OPTIONS} 
                WHERE ticker LIKE 'O:XSP{date_fmt}C%'
            """).df()
            if not neighbors.empty:
                print(f"      Found these instead: {neighbors['ticker'].tolist()}")
            else:
                print("      No Calls found for this date at all.")

    con.close()

if __name__ == "__main__":
    diagnose()