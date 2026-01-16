import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ==============================================================================
# 2. AUDIT LOGIC
# ==============================================================================
def audit_database():
    print(f"\n🛡️  QUANT OS DATA AUDIT PROTOCOL (DEEP INSPECTION)")
    print(f"    Target: {config.DB_FILE}")
    print("="*80)

    if not config.DB_FILE.exists():
        print(f"❌ CRITICAL: Database file not found at {config.DB_FILE}")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        
        if not tables:
            print("⚠️  Database is empty.")
            con.close()
            return

        for tbl in tables:
            print(f"\n📊 TABLE: {tbl}")
            print("-" * 40)
            
            # 1. COUNT & FRESHNESS
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                cols = [x[0] for x in con.execute(f"DESCRIBE {tbl}").fetchall()]
                date_col = next((c for c in cols if 'time' in c or 'date' in c), None)
                
                freshness = "N/A"
                if date_col:
                    max_date = con.execute(f"SELECT MAX({date_col}) FROM {tbl}").fetchone()[0]
                    freshness = str(max_date)
                
                print(f"   ROWS: {count} | LAST UPDATE: {freshness}")
            except: print("   Error reading stats.")

            # 2. TICKER BREAKDOWN (Indices/Options Only)
            if tbl in ['indices_1m', 'options_1m', 'active_rh_log']:
                if 'ticker' in cols:
                    print("   Breakdown by Ticker:")
                    try:
                        df_tick = con.execute(f"SELECT ticker, COUNT(*) as cnt, MAX({date_col}) as last FROM {tbl} GROUP BY ticker ORDER BY cnt DESC LIMIT 5").df()
                        print(df_tick.to_string(index=False))
                    except: pass
                elif 'root' in cols: # RH Ledger
                    print("   Breakdown by Root:")
                    try:
                        df_tick = con.execute(f"SELECT root, COUNT(*) as cnt, MAX({date_col}) as last FROM {tbl} GROUP BY root ORDER BY cnt DESC LIMIT 5").df()
                        print(df_tick.to_string(index=False))
                    except: pass

            # 3. TAIL INSPECTION (Last 3 Rows)
            print("   Last 3 Rows:")
            try:
                if date_col:
                    tail = con.execute(f"SELECT * FROM {tbl} ORDER BY {date_col} DESC LIMIT 3").df()
                else:
                    tail = con.execute(f"SELECT * FROM {tbl} LIMIT 3").df()
                print(tail.to_string(index=False))
            except Exception as e:
                print(f"   Could not fetch tail: {e}")

        con.close()
        print("\n✅ DEEP AUDIT COMPLETE.")

    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")

if __name__ == "__main__":
    audit_database()