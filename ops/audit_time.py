import sys
import os
import duckdb
from pathlib import Path

# Path Setup
ROOT_DIR = Path(__file__).resolve().parents[1] # Assuming ops/ folder
if not (ROOT_DIR / "src").exists():
    ROOT_DIR = Path(__file__).resolve().parent # Fallback if run from root

sys.path.append(str(ROOT_DIR))
from src.utils import config

print(f"🔍 AUDITING VAULT: {config.DB_FILE}")

con = duckdb.connect(str(config.DB_FILE), read_only=True)

try:
    # 1. Check Count
    count = con.execute(f"SELECT count(*) FROM {config.TBL_INDICES} WHERE ticker='SPX'").fetchone()[0]
    print(f"📊 Total SPX Rows: {count}")

    if count == 0:
        print("❌ FAIL: Table is empty. Ingestion script did not write data.")
    else:
        # 2. Check Raw Timestamp Structure (The Smoking Gun)
        print("\n🔎 SAMPLE DATA (First 5 rows):")
        query = f"""
            SELECT 
                *
            FROM {config.TBL_INDICES} 
            WHERE ticker='SPX'
            ORDER BY datetime_utc DESC
            LIMIT 5
        """
        results = con.execute(query).fetchall()
        
        print(f"{'TIMESTAMP':<30} | {'TYPE':<15} | {'HH:MM':<8} | {'HOUR_PART'}")
        print("-" * 70)
        for row in results:
            print(f"{str(row[0]):<30} | {row[1]:<15} | {row[2]:<8} | {row[3]}")

        # 3. Interpretation
        sample_hour = results[0][3]
        print("-" * 70)
        if sample_hour == 9 or sample_hour == 10:
            print("🚨 DIAGNOSIS: Data is stored as LOCAL (EST). RTH Check will FAIL.")
        elif sample_hour == 13 or sample_hour == 14:
            print("✅ DIAGNOSIS: Data is stored as UTC. RTH Check SHOULD PASS.")
        else:
            print(f"⚠️ DIAGNOSIS: Data is stored at unusual hour: {sample_hour}")

except Exception as e:
    print(f"❌ CRITICAL ERROR: {e}")

con.close()