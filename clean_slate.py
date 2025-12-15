import sys
import duckdb
from pathlib import Path

# ==============================================================================
# 1. PATH CONFIGURATION
# ==============================================================================
# Ensure we can find the system config regardless of where this is run
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.append(str(CURRENT_DIR))

try:
    from src.utils import config
    print(f"✅ Configuration Loaded. Target DB: {config.DB_FILE}")
except ImportError:
    print("❌ CRITICAL: Could not import system config. Run from Project Root.")
    sys.exit(1)

# ==============================================================================
# 2. PURGE PROTOCOL
# ==============================================================================
def run_purge():
    if not Path(config.DB_FILE).exists():
        print(f"⚠️  Database file not found at {config.DB_FILE}")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # Check if table exists first to avoid error
        tables = con.execute("SHOW TABLES").fetchall()
        if ('trade_manifest',) in tables:
            con.execute("DELETE FROM trade_manifest")
            print("🗑️  Trade Manifest purged (0 rows remaining).")
            print("✨  Ready for Optimized Signal Generation.")
        else:
            print("⚠️  'trade_manifest' table does not exist yet. Nothing to purge.")
            
        con.close()
        
    except Exception as e:
        print(f"❌ Database Error: {e}")

if __name__ == "__main__":
    run_purge()