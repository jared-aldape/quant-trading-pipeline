import sys
import duckdb
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
import src.pipeline.ingest_indices as ingest_indices
import src.pipeline.scan_signals as scan_signals

def perform_reset():
    print("🧨 STARTING NUCLEAR RESET OF INDICES...")
    
    # 1. FLUSH THE DB
    con = duckdb.connect(str(config.DB_FILE))
    print(f"🗑️  Dropping table {config.TBL_INDICES} (Purging tainted data)...")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_INDICES}")
    con.close()
    
    # 2. RECAPTURE (This uses the new PST-Aware logic in ingest_indices.py)
    print("🔄 Recapturing Data from YFinance...")
    ingest_indices.run_pipeline()
    
    # 3. REGENERATE SIGNALS (Align Manifest to New Data timeline)
    print("🚦 Regenerating Signals...")
    scan_signals.scan_and_generate_manifest()
    
    print("✅ Reset Complete. Data and Signals are clean.")

if __name__ == "__main__":
    perform_reset()