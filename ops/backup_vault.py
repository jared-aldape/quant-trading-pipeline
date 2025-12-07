import shutil
import sys
import os
import time
from pathlib import Path
from datetime import datetime

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: ops/backup_vault.py
# Location: Project Root/ops/
# Root Calculation: Go up one level from 'ops' to Project Root
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BlackBoxRecorder")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
BACKUP_DIR = config.DATA_DIR / "backups"
MAX_BACKUPS = 7  # Rolling window: Keep last 7 days

def run_backup_procedure():
    """
    Executes the 'Black Box' backup protocol.
    1. Checks if Vault exists.
    2. Creates timestamped copy.
    3. Prunes old backups to save space.
    """
    start_time = time.time()
    
    # 1. Validation
    if not config.DB_FILE.exists():
        log.error(f"❌ Backup Failed: Vault not found at {config.DB_FILE}")
        return False

    # 2. Preparation
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"quant_strategy_{timestamp}.duckdb"
    backup_path = BACKUP_DIR / backup_name
    
    # 3. Execution (The Clone)
    try:
        log.info(f"💾 Initiating Snapshot: {backup_name}...")
        
        # Flush/Checkpoint could be added here if using a persistent connection,
        # but since we rely on file-copy, ensure no other writer is active.
        shutil.copy2(config.DB_FILE, backup_path)
        
        # Calculate size in MB
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        elapsed = time.time() - start_time
        log.info(f"✅ Snapshot Complete. Size: {size_mb:.2f} MB | Time: {elapsed:.2f}s")
        
        # 4. Rotation (The Cleanup)
        rotate_backups()
        return True
        
    except Exception as e:
        log.error(f"❌ Backup Crashed: {e}")
        return False

def rotate_backups():
    """Enforces the storage limit by deleting the oldest files."""
    try:
        # Get all duckdb backups
        backups = sorted(BACKUP_DIR.glob("quant_strategy_*.duckdb"), key=os.path.getmtime)
        
        if len(backups) > MAX_BACKUPS:
            excess = len(backups) - MAX_BACKUPS
            log.info(f"🧹 Rotation Protocol: Pruning {excess} old snapshots...")
            
            for i in range(excess):
                file_to_del = backups[i]
                try:
                    file_to_del.unlink()
                    log.info(f"   🗑️ Deleted: {file_to_del.name}")
                except Exception as e:
                    log.warning(f"   ⚠️ Could not delete {file_to_del.name}: {e}")
                    
    except Exception as e:
        log.error(f"Rotation Error: {e}")

if __name__ == "__main__":
    # Allow manual execution
    run_backup_procedure()