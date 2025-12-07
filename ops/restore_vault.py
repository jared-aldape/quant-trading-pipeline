import sys
import shutil
import duckdb
from pathlib import Path

# PATH CONSTITUTION
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("VaultRestoration")

def restore_latest_backup():
    # 1. FIND BACKUP
    backup_dir = config.DATA_DIR / "backups"
    if not backup_dir.exists():
        log.error("❌ No backup directory found.")
        return

    # Sort by time (newest first)
    backups = sorted(backup_dir.glob("*.duckdb"), key=lambda f: f.stat().st_mtime, reverse=True)
    
    if not backups:
        log.error("❌ No backup files found in data/backups/")
        return

    target_backup = backups[0]
    log.info(f"📂 Found Backup: {target_backup.name}")

    # 2. RESTORE FILE
    log.info(f"♻️ Restoring to {config.DB_FILE}...")
    try:
        shutil.copy2(target_backup, config.DB_FILE)
        log.info("✅ File Restored.")
    except Exception as e:
        log.error(f"❌ Restore Failed: {e}")
        return

    # 3. PATCH SCHEMA (Add the new table non-destructively)
    log.info("💉 Patching Schema with 'live_trade_ledger'...")
    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # Check if table exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        
        if config.TBL_LIVE_LOG not in tables:
            con.execute(f"""
            CREATE TABLE {config.TBL_LIVE_LOG} (
                trade_id VARCHAR PRIMARY KEY,
                entry_time TIMESTAMP,
                exit_time TIMESTAMP,
                ticker VARCHAR,
                direction VARCHAR,
                asset_type VARCHAR,
                qty INTEGER,
                entry_price DOUBLE,
                exit_price DOUBLE,
                gross_pnl DOUBLE,
                fees_comm DOUBLE,
                net_pnl DOUBLE,
                return_pct DOUBLE,
                strategy_tag VARCHAR,
                notes VARCHAR
            )""")
            log.info(f"✅ Table '{config.TBL_LIVE_LOG}' created successfully.")
        else:
            log.info(f"ℹ️ Table '{config.TBL_LIVE_LOG}' already exists.")
            
        con.close()
        
    except Exception as e:
        log.error(f"❌ Schema Patch Failed: {e}")

if __name__ == "__main__":
    restore_latest_backup()