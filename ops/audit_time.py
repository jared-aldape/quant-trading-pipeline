import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def audit_timestamps():
    print("🕵️  TIMEZONE FORENSICS REPORT")
    print("==================================================")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    target_date = '2025-11-26'
    
    # 1. CHECK INDICES (SPX) - The Suspect
    print(f"\n📊 SPX DATA (First 5 Rows on {target_date})")
    print("   Target: We expect ~14:30 UTC (which is 09:30 EST)")
    print("-" * 50)
    
    try:
        df_spx = con.execute(f"""
            SELECT datetime_utc, open, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'SPX' 
              AND CAST(datetime_utc AS DATE) = '{target_date}'
            ORDER BY datetime_utc ASC 
            LIMIT 5
        """).df()
        
        if df_spx.empty:
            print("❌ NO SPX DATA FOUND.")
        else:
            print(df_spx)
    except Exception as e:
        print(f"Error reading SPX: {e}")

    # 2. CHECK OPTIONS (Reference) - The Truth
    print(f"\n💎 OPTION DATA (First 5 Rows on {target_date})")
    print("   Target: We expect ~14:30 UTC")
    print("-" * 50)
    
    try:
        # Get a ticker that actually exists
        ticker = con.execute(f"SELECT ticker FROM {config.TBL_OPTIONS} LIMIT 1").fetchone()
        if ticker:
            ticker_name = ticker[0]
            df_opt = con.execute(f"""
                SELECT datetime_utc, open, close 
                FROM {config.TBL_OPTIONS} 
                WHERE ticker = '{ticker_name}' 
                  AND CAST(datetime_utc AS DATE) = '{target_date}'
                ORDER BY datetime_utc ASC 
                LIMIT 5
            """).df()
            print(f"Contract: {ticker_name}")
            print(df_opt)
        else:
            print("❌ NO OPTIONS DATA FOUND.")
            
    except Exception as e:
        print(f"Error reading Options: {e}")

    con.close()
    print("\n==================================================")

if __name__ == "__main__":
    audit_timestamps()