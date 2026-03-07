import sys
import os
from pathlib import Path
from datetime import datetime
import pytz

# Setup Pathing
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger
from src.data import reset_manifest, engine_ingestion
from src.core import magitek_engine_v2

log = get_logger("BootProtocol")

def run_startup_sequence():
    log.info("🛫 INITIATING AUTOMATED SNIPER BOOT SEQUENCE...")
    
    # --- STEP 1: THE SURGICAL HARVEST (Gap Filling) ---
    # We automatically ingest the last 48 hours to ensure no NaNs in the context
    log.info("📡 STEP 1: Re-hydrating Vault (Last 48 Hours)...")
    try:
        engine_ingestion.run_sync(days_back=2) 
        log.info("✅ Vault Re-hydrated.")
    except Exception as e:
        log.error(f"❌ Ingestion Failed: {e}")

    # --- STEP 2: THE CLEAN SLATE (Reset) ---
    # Purge old simulation data so today's signals are "First Strike" clean
    log.info("🧹 STEP 2: Purging old Manifest & Resetting Slate...")
    try:
        reset_manifest.run_reset()
        log.info("✅ Manifest Reset Complete.")
    except Exception as e:
        log.error(f"❌ Reset Failed: {e}")

    # --- STEP 3: INTEGRATION INTO MAIN PIPELINE ---
    # We now trigger the Apex Sniper for the current session
    log.info("🎯 STEP 3: Deploying Apex Sniper...")
    pst = pytz.timezone('America/Los_Angeles')
    now_pst = datetime.now(pst)
    
    # If the market is open (or about to open), start the sniper
    if now_pst.hour >= 6:
        log.info("🚀 Market Gate is Active. Running First-Strike Session...")
        magitek_engine_v2.run_apex_session(
            start_dt=datetime.now(pytz.UTC) - timedelta(hours=24),
            end_dt=datetime.now(pytz.UTC)
        )
    else:
        log.info("⏳ Market Gate Closed. Sniper standing by for 06:40 PST...")

if __name__ == "__main__":
    run_startup_sequence()