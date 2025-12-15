import duckdb
import pandas as pd
from src.utils import config

def run_debug():
    print("⚔️  DEBUG PROTOCOL: SIGNAL VS REALITY")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. Pick a MACRO Signal from the Manifest
    print("\n1. INSPECTING MACRO SIGNAL...")
    sig = con.execute("""
        SELECT date, trade_type, xsp_price 
        FROM trade_manifest 
        WHERE signal_type LIKE 'MACRO%' 
        LIMIT 1
    """).df()
    
    if sig.empty:
        print("❌ No Macro signals found in Manifest.")
        return

    target_date = sig.iloc[0]['date']
    target_price = sig.iloc[0]['xsp_price']
    trade_type = sig.iloc[0]['trade_type']
    
    print(f"   Target Date: {target_date}")
    print(f"   Target Underlying: ${target_price:.2f}")
    print(f"   Trade Type: {trade_type}")

    # 2. Check What Options Actually Exist for That Day
    print(f"\n2. CHECKING VAULT FOR {target_date}...")
    
    # Query options for that specific date
    opts = con.execute(f"""
        SELECT ticker, strike, type, open 
        FROM options_1m 
        WHERE CAST(datetime_utc AS DATE) = '{target_date}' 
        LIMIT 5
    """).df()
    
    if opts.empty:
        print("❌ CRITICAL: No options data found for this date.")
        print("   -> Possible Cause: 'backfill_history.py' did not cover this specific date.")
    else:
        print(f"   ✅ Found {len(opts)} options (Sample):")
        print(opts)
        
        # 3. Test Reconstruction Logic
        print("\n3. TESTING RECONSTRUCTION LOGIC...")
        strike_raw = round(target_price)
        strike_str = f"{int(strike_raw * 1000):08d}"
        date_str = pd.to_datetime(target_date).strftime('%y%m%d')
        opt_type = 'P' if trade_type == 'put' else 'C'
        
        constructed_ticker = f"O:XSP{date_str}{opt_type}{strike_str}"
        print(f"   System generated ticker: {constructed_ticker}")
        
        # Check if this specific constructed ticker exists
        exists = con.execute(f"SELECT count(*) FROM options_1m WHERE ticker = '{constructed_ticker}'").fetchone()[0]
        if exists:
            print("   ✅ MATCH CONFIRMED. Ticker exists in DB.")
        else:
            print("   ❌ MATCH FAILED. Ticker not found in DB.")
            print("   -> Action: We need to align the 'reconstruct_ticker' logic with the DB format.")

    con.close()

if __name__ == "__main__":
    run_debug()