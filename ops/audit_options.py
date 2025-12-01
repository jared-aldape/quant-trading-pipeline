import sys
import duckdb
import pandas as pd
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def audit_specific_date(target_date_str="2025-11-24"):
    print(f"🕵️ AUDITING OPTIONS FOR: {target_date_str}")
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. Get all tickers for this date
    try:
        df = con.execute(f"""
            SELECT ticker, count(*) as bar_count, min(open) as sample_price
            FROM {config.TBL_OPTIONS}
            WHERE CAST(datetime_utc AS DATE) = '{target_date_str}'
            GROUP BY ticker
            ORDER BY ticker
        """).df()
        
        if df.empty:
            print("❌ NO OPTION DATA FOUND for this date.")
        else:
            print(f"✅ Found {len(df)} contract(s):")
            print(df.to_string(index=False))
            
    except Exception as e:
        print(f"Audit Error: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    # Defaulting to the date in your screenshot
    audit_specific_date("2025-11-24")