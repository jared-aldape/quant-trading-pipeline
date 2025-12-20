import sys
from pathlib import Path
import time

# SETUP PATHS (Adjusted for being in 'ops/')
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger
from src.data import ingest_indices

log = get_logger("LiveRefresh")

def run_tactical_update():
    """
    Executes a surgical data update for the Live Scope Dashboard.
    - Skips ML Training
    - Skips Historical Backtesting
    - Skips Option Chain Harvesting
    - Focuses PURELY on XSP/VIX Candles for the Chart.
    """
    start_time = time.time()
    log.info("⚡ TACTICAL DATA REFRESH INITIATED...")

    try:
        # Run Index Ingestion in 'Fast Mode' (Last 5 days)
        # This updates 'live_snapshot.json' immediately.
        ingest_indices.run_ingest(lookback_days=5)
        
        elapsed = time.time() - start_time
        log.info(f"✅ REFRESH COMPLETE. Data updated in {elapsed:.2f}s.")
        
    except Exception as e:
        log.error(f"❌ REFRESH FAILED: {e}")

if __name__ == "__main__":
    run_tactical_update()