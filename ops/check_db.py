import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# Corrected for location: quant-trading-pipeline/ops/check_db.py
# We use .parents[1] because the file is only 1 folder deep from Root.
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def check_integrity():
    print(f"🏥 DATA VAULT DIAGNOSTIC")
    print(f"📂 Database: {config.DB_FILE}")
    print("=" * 60)
    
    if not config.DB_FILE.exists():
        print(f"❌ CRITICAL: Database file not found at {config.DB_FILE}")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. GET TABLE LIST
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
        print(f"🔎 Found Tables: {', '.join(table_names)}")
        print("-" * 60)
    except Exception as e:
        print(f"❌ Error listing tables: {e}")
        return

    # 2. CHECK INDICES (SPX, VIX)
    if config.TBL_INDICES in table_names:
        print(f"📊 TABLE: {config.TBL_INDICES}")
        try:
            # Group by ticker to see breakdown
            df = con.execute(f"""
                SELECT 
                    ticker, 
                    COUNT(*) as rows, 
                    MIN(datetime_utc) as start_date, 
                    MAX(datetime_utc) as end_date 
                FROM {config.TBL_INDICES} 
                GROUP BY ticker
            """).df()
            print(df.to_string(index=False))
        except Exception as e:
            print(f"   ⚠️ Query Error: {e}")
    else:
        print(f"⚠️ MISSING TABLE: {config.TBL_INDICES}")
    print("-" * 60)

    # 3. CHECK OPTIONS (XSP)
    if config.TBL_OPTIONS in table_names:
        print(f"📊 TABLE: {config.TBL_OPTIONS}")
        try:
            # Summary stats for options
            res = con.execute(f"""
                SELECT 
                    COUNT(*) as total_rows, 
                    COUNT(DISTINCT ticker) as unique_contracts, 
                    MIN(datetime_utc) as first_data, 
                    MAX(datetime_utc) as last_data
                FROM {config.TBL_OPTIONS}
            """).fetchone()
            
            print(f"   Total Rows:       {res[0]:,}")
            print(f"   Unique Contracts: {res[1]:,}")
            print(f"   Date Range:       {res[2]} -> {res[3]}")
            
            # Check for specific holes (e.g. valid price but 0 volume is fine, but 0 price is bad)
            bad_rows = con.execute(f"SELECT COUNT(*) FROM {config.TBL_OPTIONS} WHERE close <= 0").fetchone()[0]
            if bad_rows > 0:
                print(f"   ⚠️ WARNING: Found {bad_rows} rows with Price <= 0")
            else:
                print(f"   ✅ Price Integrity Check Passed")
                
        except Exception as e:
            print(f"   ⚠️ Query Error: {e}")
    else:
        print(f"⚠️ MISSING TABLE: {config.TBL_OPTIONS}")
    print("-" * 60)

    # 4. CHECK MANIFEST (Signals)
    if config.TBL_MANIFEST in table_names:
        print(f"📊 TABLE: {config.TBL_MANIFEST}")
        try:
            df = con.execute(f"""
                SELECT 
                    signal_type,
                    COUNT(*) as count, 
                    MIN(date) as first_signal, 
                    MAX(date) as last_signal
                FROM {config.TBL_MANIFEST}
                GROUP BY signal_type
            """).df()
            print(df.to_string(index=False))
        except Exception as e:
            print(f"   ⚠️ Query Error: {e}")
    else:
        print(f"⚠️ MISSING TABLE: {config.TBL_MANIFEST}")
        
    con.close()
    print("=" * 60)
    print("✅ Diagnostic Complete.")

if __name__ == "__main__":
    check_integrity()