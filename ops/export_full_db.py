import sys
import duckdb
import os
from datetime import datetime
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
    # Fallback config if running standalone
    class MockConfig:
        DB_FILE = ROOT_DIR / "data" / "quant_strategy.duckdb"
    config = MockConfig()
    
    import logging
    logging.basicConfig(level=logging.INFO)
    def get_logger(name): return logging.getLogger(name)

log = get_logger("DB_Export")

# ==============================================================================
# 2. EXPORT LOGIC
# ==============================================================================
def run_export():
    if not config.DB_FILE.exists():
        log.error(f"❌ Database not found at: {config.DB_FILE}")
        return

    # Create a Timestamped Export Directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    export_dir = ROOT_DIR / "exports" / f"dump_{timestamp}"
    export_dir.mkdir(parents=True, exist_ok=True)
    
    log.info(f"📂 Target Directory: {export_dir}")
    log.info(f"🔌 Connecting to Vault: {config.DB_FILE.name}")

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Get List of All Tables
        tables = con.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
        
        if not table_names:
            log.warning("⚠️ Database is empty (No tables found).")
            return

        log.info(f"🔍 Found {len(table_names)} tables: {', '.join(table_names)}")

        # 2. Export Loop
        for table in table_names:
            csv_path = export_dir / f"{table}.csv"
            log.info(f"   ⬇️ Exporting {table}...")
            
            # Efficient DuckDB COPY command
            con.execute(f"COPY {table} TO '{str(csv_path)}' (HEADER, DELIMITER ',')")
            
            # Validation (Check file size)
            size_mb = csv_path.stat().st_size / (1024 * 1024)
            log.info(f"      ✅ Saved: {csv_path.name} ({size_mb:.2f} MB)")

        con.close()
        log.info("--------------------------------------------------")
        log.info(f"🎉 FULL EXPORT COMPLETE. Location: {export_dir}")

    except Exception as e:
        log.critical(f"❌ EXPORT FAILED: {e}")

if __name__ == "__main__":
    run_export()