import sys
import duckdb
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("ManifestReset")

def run_reset():
    if not config.DB_FILE.exists():
        log.error("❌ No Database found to reset.")
        return

    log.warning("⚠️ INITIATING MANIFEST PURGE...")
    con = duckdb.connect(str(config.DB_FILE))
    
    try:
        # 1. DROP THE TABLES (The Nuclear Option)
        # This removes all traces of old, bad, or ghost signals.
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
        con.execute(f"DROP TABLE IF EXISTS signal_history_log")
        
        log.info("✅ Dropped 'option_signal_manifest'")
        log.info("✅ Dropped 'signal_history_log'")
        
        # 2. RECREATE EMPTY SCHEMA
        # We recreate them so the next pipeline run has a clean container to fill.
        
        # Manifest (Execution Queue)
        con.execute(f"""
            CREATE TABLE {config.TBL_MANIFEST} (
                entry_timestamp_utc BIGINT,
                date DATE,
                signal_type VARCHAR,
                xsp_price DOUBLE,
                trade_type VARCHAR,
                meta_data VARCHAR,
                allocation_pct DOUBLE,
                PRIMARY KEY (entry_timestamp_utc, trade_type)
            )
        """)
        
        # History Log (Audit Trail)
        con.execute(f"""
            CREATE TABLE signal_history_log (
                timestamp_utc TIMESTAMP,
                ticker VARCHAR,
                signal_type VARCHAR,
                vix_value DOUBLE,
                rsi_value DOUBLE,
                market_regime VARCHAR,
                flow_bias VARCHAR,
                meta_data VARCHAR,
                PRIMARY KEY (timestamp_utc, ticker)
            )
        """)
        
        log.info("✨ Tables recreated. The slate is clean.")
        log.info("👉 NEXT STEP: Run 'main_pipeline.py' to generate fresh, clean signals.")

    except Exception as e:
        log.error(f"Reset Failed: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    run_reset()