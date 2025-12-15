import sys
import duckdb
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
except ImportError:
    # Minimal fallback
    print("❌ CRITICAL: Could not import 'src.utils'.")
    sys.exit(1)

log = get_logger("SchemaCheck")

def run_check():
    log.info(f"🔍 Checking Schema and Sample Data for: {config.TBL_MANIFEST}")
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Describe the table (show all columns)
        log.info("--- TABLE STRUCTURE ---")
        cols = con.execute(f"DESCRIBE {config.TBL_MANIFEST}").fetchall()
        for col in cols:
            log.info(f"Column: {col[0]} | Type: {col[1]}")
            
        # 2. Show a sample row (to check data types/nulls)
        log.info("--- SAMPLE ROW (First 1) ---")
        sample = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} LIMIT 1").df()
        
        if sample.empty:
            log.warning("⚠️ Table is empty! Scanner likely failed to commit.")
        else:
            print(sample.to_markdown(index=False))

        con.close()
        
    except Exception as e:
        log.error(f"❌ DATABASE CHECK FAILED: {e}")
        log.error("HINT: Ensure the table name 'trade_manifest' is correct.")

if __name__ == "__main__":
    run_check()