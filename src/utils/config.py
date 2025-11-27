import os
import requests
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION (Project-Relative)
# ==============================================================================
# Resolves to: quant-trading-pipeline/src/utils/config.py
CURRENT_FILE = Path(__file__).resolve()

# Resolves to: quant-trading-pipeline/
PROJECT_ROOT = CURRENT_FILE.parent.parent.parent

# Centralized Data Volumes
DATA_DIR = PROJECT_ROOT / "market_data"
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"  # Artifact Storage
SRC_DIR = PROJECT_ROOT / "src"

# Enforce Existence (The Integrity Law)
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Database & Log Paths
DB_FILE = DATA_DIR / "quant_strategy.duckdb"
LOG_FILE = LOGS_DIR / "pipeline.log"

# ==============================================================================
# 2. API CREDENTIALS
# ==============================================================================
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "nXc9zGHMXbtKtum0EXEM2vpTf4TCeoxd")

# ==============================================================================
# 3. TIMEZONE CONSTITUTION
# ==============================================================================
# "UTC in the Vault, Local on the Glass"
TZ_UTC = pytz.utc
TZ_NY = pytz.timezone('America/New_York')
TZ_LOCAL = pytz.timezone('US/Pacific')

# ==============================================================================
# 4. DATABASE SCHEMA CONSTANTS
# ==============================================================================
TBL_INDICES = "indices_1m"       # SPX, VIX
TBL_OPTIONS = "options_1m"       # XSP
TBL_MANIFEST = "trade_manifest"  # Signals
TBL_FUTURES = "futures_1m"       # ES=F
TBL_IRX = "risk_free_rate_daily" # Risk Free Rate

# ==============================================================================
# 5. GLOBAL NETWORK SESSION (Anti-Rate-Limit)
# ==============================================================================
# Masquerade as a standard Chrome browser to avoid being blocked by Yahoo.
# Use this session (config.GLOBAL_SESSION) for all yf.download calls.
GLOBAL_SESSION = requests.Session()
GLOBAL_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})