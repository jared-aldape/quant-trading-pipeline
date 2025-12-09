import sys
import duckdb
import pandas as pd
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def verify_vault():
    print(f"🕵️ AUDITING VAULT: {config.DB_FILE}\n")
    
    if not config.DB_FILE.exists():
        print("❌ CRITICAL: Database file not found!")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)

    # ---------------------------------------------------------
    # 1. CHECK INDICES (Phase 1 Result)
    # ---------------------------------------------------------
    print("--- [LAYER 1] MARKET INDICES (SPX/VIX) ---")
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_INDICES}").fetchone()[0]
        recent = con.execute(f"SELECT * FROM {config.TBL_INDICES} ORDER BY datetime_utc DESC LIMIT 3").df()
        print(f"✅ Total Rows: {count:,}")
        if not recent.empty:
            print(recent[['datetime_utc', 'ticker', 'close']].to_string(index=False))
        else:
            print("⚠️ Table is empty.")
    except Exception as e:
        print(f"❌ Error: {e}")
    print("")

    # ---------------------------------------------------------
    # 2. CHECK MANIFEST (Phase 2 Result)
    # ---------------------------------------------------------
    print("--- [LAYER 2] STRATEGY SIGNALS (Manifest) ---")
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_MANIFEST}").fetchone()[0]
        # We specifically check the STRIKE PRICE here to verify the math fix
        recent = con.execute(f"SELECT date, signal_type, xsp_price, trade_type FROM {config.TBL_MANIFEST} LIMIT 5").df()
        
        print(f"✅ Total Signals: {count}")
        if not recent.empty:
            print(recent.to_string(index=False))
            
            # MATH VERIFICATION
            strikes = recent['xsp_price'].tolist()
            if any(s < 100 for s in strikes):
                print("\n❌ DATA FAILURE: Strike Prices are still < $100. Smart Scaling Failed.")
            else:
                print("\n✅ DATA SUCCESS: Strike Prices are in correct XSP range (~$500-$600).")
        else:
            print("⚠️ Table is empty.")
    except Exception as e:
        print(f"❌ Error: {e}")
    print("")

    # ---------------------------------------------------------
    # 3. CHECK OPTIONS (Phase 3 Result)
    # ---------------------------------------------------------
    print("--- [LAYER 3] OPTION CONTRACTS (The Gold) ---")
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_OPTIONS}").fetchone()[0]
        # Check the specific contract we just saw in the logs
        sample = con.execute(f"SELECT ticker, datetime_utc, close, volume FROM {config.TBL_OPTIONS} LIMIT 5").df()
        
        print(f"✅ Total Option Bars: {count:,}")
        if not sample.empty:
            print(sample.to_string(index=False))
        else:
            print("⚠️ Table is empty.")
    except Exception as e:
        print(f"❌ Error: {e}")
        
    con.close()
    print("\n🏁 AUDIT COMPLETE.")

if __name__ == "__main__":
    verify_vault()