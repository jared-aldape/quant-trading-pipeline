import os
from pathlib import Path
import pytz

# ==========================================
# 1. PATH CONFIGURATION
# ==========================================
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent.parent.parent

DATA_DIR = PROJECT_ROOT / "market_data"
LOGS_DIR = PROJECT_ROOT / "logs"
SRC_DIR = PROJECT_ROOT / "src"

# Ensure directory structure exists
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = DATA_DIR / "quant_strategy.duckdb"
LOG_FILE = LOGS_DIR / "pipeline.log"

# ==========================================
# 2. API CREDENTIALS
# ==========================================
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "nXc9zGHMXbtKtum0EXEM2vpTf4TCeoxd")

# ==========================================
# 3. TIMEZONE CONSTITUTION
# ==========================================
TZ_UTC = pytz.utc
TZ_NY = pytz.timezone('America/New_York')
TZ_LOCAL = pytz.timezone('US/Pacific')

# ==========================================
# 4. DATABASE SCHEMA CONSTANTS
# ==========================================
TBL_INDICES = "indices_1m"       # SPX, VIX (Yahoo)
TBL_OPTIONS = "options_1m"       # XSP (Polygon)
TBL_MANIFEST = "trade_manifest"  # Signals
TBL_FUTURES = "futures_1m"       # ES=F (Yahoo - Overnight Context)
TBL_IRX = "risk_free_rate_daily" # ^IRX (Yahoo - 13 Week T-Bill)