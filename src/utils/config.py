import os
import requests
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION (Project-Relative)
# ==============================================================================
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

DATA_DIR = PROJECT_ROOT / "data"      
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"
SRC_DIR = PROJECT_ROOT / "src"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = DATA_DIR / "quant_strategy.duckdb"
LOG_FILE = LOGS_DIR / "system.log"

# ==============================================================================
# 2. API CREDENTIALS
# ==============================================================================
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "nXc9zGHMXbtKtum0EXEM2vpTf4TCeoxd") 

# ==============================================================================
# 3. TIMEZONE CONSTITUTION
# ==============================================================================
TZ_UTC = pytz.utc
TZ_NY = pytz.timezone('America/New_York')
TZ_LOCAL = pytz.timezone('US/Pacific')

# ==============================================================================
# 4. DATABASE SCHEMA CONSTANTS
# ==============================================================================
TBL_INDICES = "indices_1m"       
TBL_OPTIONS = "options_1m"       
TBL_FUTURES = "futures_1m"       
TBL_IRX = "risk_free_rate_daily" 

TBL_MANIFEST = "trade_manifest"       
TBL_SIM_LOG = "active_simulation_log" 
TBL_MACRO_FLOW = "macro_flow_state"   

# ==============================================================================
# 5. BROKER FEES (Robinhood / Regulatory)
# ==============================================================================
# Source: User provided Robinhood Fee Schedule (May 2025 / Jan 2026)
RH_FEES = {
    "REGULATORY_BASE": 0.04,  # Options Regulatory Fee (ORF) + OCC Clearing
    "CONTRACT_GOLD": 0.35,    # RH Gold Contract Fee
    "CONTRACT_STD": 0.50,     # RH Standard Contract Fee
    "INDEX_EXCHANGE": 0.07,   # CBOE Prop Fee (XSP >= 10 contracts)
    "EQUITY_TAF": 0.00279,    # FINRA Trading Activity Fee (Sells only)
    "TAF_CAP": 8.30           # Max TAF per trade
}

# ==============================================================================
# 6. GLOBAL NETWORK SESSION
# ==============================================================================
GLOBAL_SESSION = requests.Session()
GLOBAL_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})

TICKERS_INDICES = ['I:SPX', 'I:VIX']
TICKERS_IRX = ['I:IRX']