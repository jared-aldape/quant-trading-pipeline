import sys
from pathlib import Path
import datetime

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_ml
from src.utils.logger import get_logger

log = get_logger("TrainScheduler")

def auto_train():
    log.info("🧠 Starting Weekly Auto-Training Protocol...")
    try:
        model = engine_ml.train_oracle()
        if model:
            log.info("✅ Training Complete. Model weights updated.")
        else:
            log.warning("⚠️ Training skipped (Insufficient Data/Error).")
    except Exception as e:
        log.error(f"❌ Training Failed: {e}")

if __name__ == "__main__":
    # Check if it's Friday (Day 4) and after market close (optional logic)
    # For now, we assume this script is triggered by cron
    auto_train()