import sys
import duckdb
import pandas as pd
import requests
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("DeepProbe")

def run_probe():
    if not config.DB_FILE.exists():
        log.error("❌ No Database found.")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    try:
        # ---------------------------------------------------------
        # 1. SCHEMA INSPECTION
        # ---------------------------------------------------------
        log.info("--- 1. TABLE SCHEMA (indices_1m) ---")
        schema = con.execute(f"DESCRIBE {config.TBL_INDICES}").df()
        print(schema.to_string(index=False))
        print("-" * 50)
        
        # ---------------------------------------------------------
        # 2. DATA TAIL INSPECTION
        # ---------------------------------------------------------
        log.info("--- 2. SPX DATA TAIL (Last 5 Rows) ---")
        tail = con.execute(f"""
            SELECT * FROM {config.TBL_INDICES} 
            WHERE ticker = 'SPX' 
            ORDER BY datetime_utc DESC 
            LIMIT 5
        """).df()
        
        if not tail.empty:
            print(tail.to_string(index=False))
        else:
            log.warning("⚠️ No SPX data found to inspect.")
        print("-" * 50)
        
        # ---------------------------------------------------------
        # 3. API LIVE PROBE
        # ---------------------------------------------------------
        log.info("--- 3. POLYGON API PROBE (2025-12-09) ---")
        # We try to fetch 1 single minute of data to see the raw error
        target_url = "https://api.polygon.io/v2/aggs/ticker/I:SPX/range/1/minute/2025-12-09/2025-12-09"
        params = {
            "adjusted": "true", 
            "sort": "asc", 
            "limit": 10, 
            "apiKey": config.POLYGON_API_KEY
        }
        
        log.info(f"📡 Sending Request to: {target_url}")
        resp = requests.get(target_url, params=params, timeout=10)
        
        log.info(f"Status Code: {resp.status_code}")
        try:
            data = resp.json()
            # print raw json key info (avoid massive dump if huge)
            log.info(f"Response Keys: {list(data.keys())}")
            if 'results' in data:
                log.info(f"Results Count: {len(data['results'])}")
                if len(data['results']) == 0:
                    log.warning("⚠️ API returned 'results': [] (Empty List). Data does not exist at source.")
            elif 'status' in data:
                log.info(f"API Status: {data['status']}")
                if 'message' in data:
                     log.warning(f"API Message: {data['message']}")
        except Exception as e:
            log.error(f"Failed to parse JSON: {e}")
            print(resp.text)

    except Exception as e:
        log.error(f"Probe Failed: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    run_probe()