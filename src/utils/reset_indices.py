import duckdb
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SystemReset")

def wipe_indices_and_signals():
    print("="*60)
    print("🧹 SURGICAL DATA WIPE: INDICES & SIGNALS")
    print("="*60)
    print(f"🎯 Target DB: {config.DB_FILE}")
    print("⚠️  OPTIONS DATA WILL BE PRESERVED.")
    
    if not config.DB_FILE.exists():
        log.error("❌ Database file not found!")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. WIPE INDICES (SPX, VIX)
    try:
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_INDICES}")
        log.info(f"✅ DROPPED TABLE: {config.TBL_INDICES} (Indices Data Wiped)")
    except Exception as e:
        log.error(f"❌ Error dropping indices: {e}")

    # 2. WIPE SIGNALS (Manifest)
    try:
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
        log.info(f"✅ DROPPED TABLE: {config.TBL_MANIFEST} (Signal History Wiped)")
    except Exception as e:
        log.error(f"❌ Error dropping manifest: {e}")

    # 3. VERIFY OPTIONS ARE SAFE (Optional Check)
    # Assuming options are in 'option_chain' or similar, we just don't touch them.
    
    con.close()
    print("-" * 60)
    print("✅ RESET COMPLETE. INDICES ARE GONE.")
    print("👉 NEXT STEPS:")
    print("   1. Run 'engine_ingestion.py' to re-download fresh SPX/VIX data.")
    print("   2. Run 'engine_scanner.py' to re-generate signals.")
    print("="*60)

if __name__ == "__main__":
    confirm = input("Are you sure you want to delete all Index and Signal data? (y/n): ")
    if confirm.lower() == 'y':
        wipe_indices_and_signals()
    else:
        print("❌ Operation Cancelled.")