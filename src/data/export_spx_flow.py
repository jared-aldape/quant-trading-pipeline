import sys
import duckdb
from pathlib import Path
import os # Import os for environment check

# ==============================================================================
# 1. PATH CONSTITUTION (Standard Project Setup)
# ==============================================================================
# File Location: src/data/export_spx_flow.py
# Root Location: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SPXExporter")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
OUTPUT_CSV_NAME = "spx_daily_flow_data.csv"

def run_export():
    """
    Connects to the DuckDB Vault and exports SPX minute data 
    (datetime_utc, open, close) for Macro Flow analysis.
    """
    log.info(f"🔌 Attempting to connect to Vault: {config.DB_FILE}")
    
    # 1. Ensure the DB file exists
    if not os.path.exists(config.DB_FILE):
        log.error(f"❌ CRITICAL ERROR: Database file not found at {config.DB_FILE}")
        log.error("Run main_pipeline.py first to create and populate the database.")
        return

    # 2. Define the output path in the centralized data directory
    output_path = config.DATA_DIR / OUTPUT_CSV_NAME
    
    # 3. SQL Query for Export
    # We use the COPY command for native, fast file export from DuckDB
    export_query = f"""
    COPY (
        SELECT 
            datetime_utc, 
            open, 
            close 
        FROM 
            {config.TBL_INDICES} 
        WHERE 
            ticker = 'SPX'
        ORDER BY 
            datetime_utc ASC
    ) TO '{output_path}' (HEADER, DELIMITER ',');
    """

    try:
        con = duckdb.connect(str(config.DB_FILE))
        log.info(f"🔎 Executing query to extract SPX data from {config.TBL_INDICES}...")
        
        # Execute the query
        con.execute(export_query)
        con.close()
        
        log.info(f"✅ SUCCESS: SPX data exported.")
        log.info(f"   File saved to: {output_path}")

    except duckdb.CatalogException as e:
        log.error(f"❌ ERROR: DuckDB Catalog Error (Table missing or columns incorrect). Details: {e}")
        log.error("Check if 'indices_1m' table exists and contains 'SPX' data.")
    except Exception as e:
        log.error(f"❌ CRITICAL EXPORT ERROR: {e}")

if __name__ == '__main__':
    run_export()