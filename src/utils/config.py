import os
import requests
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION (Environment Aware)
# ==============================================================================
CURRENT_FILE = Path(__file__).resolve()

# DETECT ENVIRONMENT:
# Check if the specific AWS production folder exists.
if Path("/home/ubuntu/QUANT-OS").exists():
    # We are on the AWS Cloud Node -> Force Absolute Path
    PROJECT_ROOT = Path("/home/ubuntu/QUANT-OS")
else:
    # We are on Local Windows -> Calculate relative path
    # src/utils/config.py -> parents[0]=utils, parents[1]=src, parents[2]=ROOT
    PROJECT_ROOT = CURRENT_FILE.parents[2]

DATA_DIR = PROJECT_ROOT / "data"      
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"
SRC_DIR = PROJECT_ROOT / "src"

# Ensure directories exist
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
RH_FEES = {
    "REGULATORY_BASE": 0.04,  
    "CONTRACT_GOLD": 0.35,    
    "CONTRACT_STD": 0.50,     
    "INDEX_EXCHANGE": 0.07,   
    "EQUITY_TAF": 0.00279,    
    "TAF_CAP": 8.30           
}

# ==============================================================================
# 6. GLOBAL NETWORK SESSION
# ==============================================================================
GLOBAL_SESSION = requests.Session()
GLOBAL_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})

# ==============================================================================
# 7. COMMUNICATION CHANNELS (TACTICAL ALERTING)
# ==============================================================================
# Paste your Discord Webhook URL below. 
DISCORD_WEBHOOK = "YOUR_DISCORD_WEBHOOK_URL_HERE"
ENABLE_DISCORD = True