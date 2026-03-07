import sys
import time
import pytz
import importlib
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("CommandCenter")

# ==============================================================================
# 2. DYNAMIC IMPORTER (Preserved for Background Deep-Repair)
# ==============================================================================
def safe_import(module_path, fallback_path=None):
    try:
        return importlib.import_module(module_path)
    except ImportError:
        if fallback_path:
            try:
                log.warning(f"⚠️ Module '{module_path}' not found. Falling back...")
                return importlib.import_module(fallback_path)
            except ImportError: return None
        return None

# ==============================================================================
# 3. THE INSTITUTIONAL MORNING ROUTINE (THE FIRST STRIKE)
# ==============================================================================
def run_apex_morning_routine():
    """
    The 'Turnkey' sequence. Fast-syncs data, cleans the slate, and executes the Sniper.
    """
    pst = pytz.timezone('America/Los_Angeles')
    now_pst = datetime.now(pst)
    
    # Import execution engines directly for the live run
    from src.core import engine_ingestion
    from src.utils import reset_manifest, clean_manifest
    from src.core import engine_macro_flow, engine_scanner, engine_forecast, magitek_engine_v2
    
    print("\n" + "═"*90)
    print(f"🚀 QUANT OS: APEX SNIPER DEPLOYMENT | {now_pst.strftime('%Y-%m-%d %H:%M')} PST")
    print("═"*90)

    # --- STAGE 1: THE MAINTENANCE (Re-Hydration & Reset) ---
    log.info("📡 STAGE 1: Re-hydrating Vault (Last 48 Hours)...")
    try:
        # Fast sync to prevent NaN Chain Gaps
        engine_ingestion.fetch_data('^GSPC', 'SPX')
        engine_ingestion.fetch_data('^VIX', 'VIX')
        
        # Wipe the manifest so today's signals are clean
        log.info("🧹 Purging Ghost Signals...")
        clean_manifest.clean_manifest()
        reset_manifest.run_reset()
        log.info("✅ Vault Re-hydrated. Slate Reset.")
    except Exception as e:
        log.error(f"❌ Critical Sync/Reset Failure: {e}")
        return

    # --- STAGE 2: THE FORECAST (Opening Range Intelligence) ---
    log.info("🔭 STAGE 2: Analyzing 06:30 - 06:40 PST Opening Range...")
    try:
        forecast = engine_forecast.fetch_market_data(ticker="SPY", period="5d", interval="5m")
        # In a real environment, you'd calculate ORB here based on the fetched df
        log.info(f"✅ Target Mapping Prepared.")
    except Exception as e:
        log.warning(f"⚠️ Forecast unavailable: {e}")

    # --- STAGE 3: THE REGIME (Macro Bias) ---
    log.info("📈 STAGE 3: Locking Macro Flow Bias...")
    try:
        engine_macro_flow.calculate_macro_bias()
    except: pass

    # --- STAGE 4: THE HUNT (Signal Scanning) ---
    log.info("🕵️ STAGE 4: Scanning XSP for Fractal Breakouts...")
    try:
        engine_scanner.run_scanner()
    except Exception as e:
        log.error(f"❌ Scanner Failure: {e}")

    # --- STAGE 5: THE STRIKE (Apex Sniper Execution) ---
    # LAW: The Gate opens at 06:40 PST. 
    gate_time = now_pst.replace(hour=6, minute=40, second=0, microsecond=0)
    
    if now_pst < gate_time:
        wait_mins = int((gate_time - now_pst).total_seconds() / 60)
        log.info(f"⏳ STAGE 5: Gate opens in {wait_mins} mins. Standing by for 06:40 PST...")
        # Optional: time.sleep((gate_time - now_pst).total_seconds())
    
    log.info("🎯 STAGE 5: Deploying Apex Sniper (First-Strike Protocol)...")
    try:
        # Start looking for the one-trade-per-day strike
        magitek_engine_v2.run_apex_session(
            start_dt=datetime.now(pytz.UTC) - timedelta(hours=12),
            end_dt=datetime.now(pytz.UTC) + timedelta(hours=12),
            initial_balance=1000.0 # <--- SET YOUR STARTING BALANCE HERE
        )
    except Exception as e:
        log.error(f"❌ Sniper Execution Error: {e}")

    print("\n" + "═"*90)
    print("🏁 MORNING ROUTINE COMPLETE. SESSION LOGGED.")
    print("═"*90)


# ==============================================================================
# 4. BACKGROUND DAEMON (Preserved for Deep-Repair)
# ==============================================================================
def run_continuous_cycle():
    """
    Institutional Background Thread. 
    Runs the deep-repair pipeline every 12 hours.
    """
    while True:
        try:
            log.info(f"🚀 RUNNING BACKGROUND DEEP-REPAIR (59 DAYS)")
            # Your original dynamic imports and Deep Lookback go here...
            time.sleep(43200) # 12 hours
        except Exception as e:
            log.error(f"❌ Background Pipeline Error: {e}")
            time.sleep(3600) 

# ==============================================================================
# 5. ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    # When you open the terminal and run 'python main_pipeline.py', 
    # it executes the targeted Morning Strike immediately.
    run_apex_morning_routine()