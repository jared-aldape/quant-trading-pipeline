import sys
import duckdb
import pandas as pd
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OptionsProbe")

TBL_OPTIONS = getattr(config, 'TBL_OPTIONS', 'options_1m')

def probe_options():
    log.info(f"🔬 PROBING OPTIONS DATA TABLE: {TBL_OPTIONS}")
    
    if not config.DB_FILE.exists():
        log.error("❌ Database not found.")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    try:
        # 1. CHECK EXISTENCE
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if TBL_OPTIONS not in tables:
            log.error(f"❌ Table '{TBL_OPTIONS}' NOT FOUND in Vault.")
            con.close()
            return

        # 2. GET ROW COUNT & DATE RANGE
        stats = con.execute(f"""
            SELECT 
                COUNT(*) as total_rows,
                MIN(datetime_utc) as start_date,
                MAX(datetime_utc) as end_date,
                COUNT(DISTINCT ticker) as unique_contracts
            FROM {TBL_OPTIONS}
        """).df()
        
        print("\n" + "="*60)
        print("📊 OPTIONS DATA INVENTORY")
        print("="*60)
        print(stats.to_string(index=False))
        
        # 3. SAMPLE DATA (FORMAT INSPECTION)
        print("\n" + "="*60)
        print("🧬 DNA SAMPLE (First 5 Rows)")
        print("="*60)
        
        sample = con.execute(f"SELECT * FROM {TBL_OPTIONS} LIMIT 5").df()
        print(sample.to_string(index=False))
        
        # 4. OPRA CODE ANALYSIS
        if not sample.empty:
            ticker_sample = sample.iloc[0]['ticker']
            print(f"\n🔎 TICKER FORMAT ANALYSIS: '{ticker_sample}'")
            print(f"   Length: {len(ticker_sample)}")
            if "XSP" in ticker_sample:
                print("   Asset: XSP Detected")
            if "C" in ticker_sample or "P" in ticker_sample:
                print("   Right: Option Right Detected")
                
    except Exception as e:
        log.error(f"Probe Failed: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    probe_options()