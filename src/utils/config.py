import os
import requests
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION (Project-Relative)
# ==============================================================================
# File: src/utils/config.py
# Resolves to: .../QUANT-OS/src/utils/config.py
CURRENT_FILE = Path(__file__).resolve()

# Root: .../QUANT-OS/
PROJECT_ROOT = CURRENT_FILE.parents[2]

# Centralized Data Volumes
DATA_DIR = PROJECT_ROOT / "data"      # Updated to 'data' (was 'market_data')
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"
SRC_DIR = PROJECT_ROOT / "src"

# Enforce Existence (The Integrity Law)
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Database & Log Paths
DB_FILE = DATA_DIR / "quant_strategy.duckdb"
LOG_FILE = LOGS_DIR / "system.log"

# ==============================================================================
# 2. API CREDENTIALS
# ==============================================================================
# "Hybrid Truth in the Vault."
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "nXc9zGHMXbtKtum0EXEM2vpTf4TCeoxd")

# ==============================================================================
# 3. TIMEZONE CONSTITUTION
# ==============================================================================
# "UTC in the Vault. Local on the Glass."
TZ_UTC = pytz.utc
TZ_NY = pytz.timezone('America/New_York')
TZ_LOCAL = pytz.timezone('US/Pacific')

# ==============================================================================
# 4. DATABASE SCHEMA CONSTANTS
# ==============================================================================
# Market Data
TBL_INDICES = "indices_1m"       # SPX, VIX (High Freq)
TBL_OPTIONS = "options_1m"       # XSP Options (Poly + Greeks)
TBL_FUTURES = "futures_1m"       # ES=F (Optional)
TBL_IRX = "risk_free_rate_daily" # 13-Week T-Bill (Daily)

# Strategy Engine
TBL_MANIFEST = "trade_manifest"      # Generated Signals (Scanner)
TBL_SIM_LOG = "active_simulation_log" # Backtest Results (Backtester)

# ==============================================================================
# 5. GLOBAL NETWORK SESSION (Anti-Rate-Limit)
# ==============================================================================
# "Proxy Speed on the Glass."
# Masquerade as a standard Chrome browser to avoid being blocked by Yahoo.
GLOBAL_SESSION = requests.Session()
GLOBAL_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})