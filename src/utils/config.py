import os
import requests
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION (Environment Aware)
# ==============================================================================
CURRENT_FILE = Path(__file__).resolve()

# DETECT ENVIRONMENT:
if Path("/home/ubuntu/QUANT-OS").exists():
    PROJECT_ROOT = Path("/home/ubuntu/QUANT-OS")
else:
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
TBL_LIVE_LOG = "live_trade_ledger"    # <--- NEW: The Bridge

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
# DISCORD INTEGRATION (v3.3)
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1446796399340556358/baydGMXNytREvepaKy4lZvlXgO6cvLvylDBVMBNQ1WHtwmTMc2oLz5MhYEbpzVOlJ6sv"
ENABLE_DISCORD = True

# ==============================================================================
# 8. STRATEGIC CONSTANTS (GLOBAL)
# ==============================================================================
# The Master Variable for ORB Synchronization
ORB_WINDOW_MINUTES = 30

# ==============================================================================
# 9. RISK PROTOCOLS (THE TIERED AGGRESSION ENGINE)
# ==============================================================================

def get_risk_tier(account_balance):
    """
    Returns the allowed risk percentage based on account size.
    AUTO-DETECTS 'SPRINT MODE' for small accounts.
    """
    if account_balance < 2000:
        # TIER 1: THE SPRINT ($164 -> $2000)
        # Ideology: "Aggressive Velocity." 
        # We authorize 40% risk because we need meaningful contract size.
        return 0.40  

    elif account_balance < 10000:
        # TIER 2: THE BUILD ($2000 -> $10,000)
        # Ideology: "Protect the Gains."
        return 0.20  

    else:
        # TIER 3: THE VAULT ($10,000+)
        # Ideology: "Stay Rich." The Oct 21st Shield.
        return 0.05 

# GLOBAL SAFETY NETS
FORCED_EXIT_ON_CHOP = True     # If ADX < 20, we close immediately.
MACRO_EVENT_MODE = False       # Set TRUE on Fed Days to tighten filters.

# ==============================================================================
# 10. SYSTEM METADATA
# ==============================================================================
SYSTEM_VERSION = "v3.3"