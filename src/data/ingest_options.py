import sys
import duckdb
import pandas as pd
import time
import requests
import re
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OptionIngest")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
POLYGON_KEY = config.POLYGON_API_KEY
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
MAX_RETRIES = 3

# ⚡ CONFIG CHANGE: User defined "2 up, 2 down"
STRIKE_RANGE = 2

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def parse_ticker_metadata(ticker):
    """
    Parses O:XSP231215C00460000 into components.
    """
    try:
        match = re.search(r'O:[A-Z]+(\d{6})([CP])(\d{8})', ticker)
        if match:
            date_str, type_char, strike_str = match.groups()
            exp_date = datetime.strptime(date_str, '%y%m%d').date()
            strike = float(strike_str) / 1000.0
            return exp_date, type_char, strike
    except Exception:
        pass
    return None, None, None

def construct_ticker_cluster(date_obj, xsp_price, trade_type='call'):
    """
    Returns a LIST of tickers based on Trade Type.
    Logic: Floor the price (Drop cents), then grab +/- 2 strikes.
    """
    tickers = []
    try:
        yymmdd = date_obj.strftime('%y%m%d')
        
        # ⚡ LOGIC CHANGE: Use int() to drop cents (Floor) instead of round()
        # Price 683.95 -> Strike 683
        atm_strike = int(xsp_price) 
        
        types_to_fetch = []
        if trade_type.lower() == 'call': types_to_fetch = ['C']
        elif trade_type.lower() == 'put': types_to_fetch = ['P']
        elif trade_type.lower() == 'straddle': types_to_fetch = ['C', 'P']
        else: types_to_fetch = ['C']
            
        # Range: ATM +/- 2 Strikes
        # If ATM is 683: [681, 682, 683, 684, 685]
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1): 
            strike = atm_strike + offset
            strike_str = f"{strike * 1000:08d}"
            
            for t_char in types_to_fetch:
                ticker = f"O:XSP{yymmdd}{t_char}{strike_str}"
                tickers.append(ticker)
            
    except Exception as e:
        log.error(f"Ticker construction failed: {e}")
    return tickers

def fetch_polygon_aggs(ticker, date_str):
    """
    Fetches 1-minute bars. Returns DataFrame (Always).
    """
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_KEY
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = config.GLOBAL_SESSION.get(url, params=params, timeout=15)
            
            if resp.status_code == 403:
                return pd.DataFrame() 

            if resp.status_code == 429:
                wait_time = 65 
                log.warning(f"⚠️ Rate Limit Hit on {ticker}. Pausing {wait_time}s...")
                time.sleep(wait_time)
                continue 

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                    df = pd.DataFrame(data["results"])
                    df.rename(columns={
                        't': 'datetime_utc', 'o': 'open', 'h': 'high', 
                        'l': 'low', 'c': 'close', 'v': 'volume'
                    }, inplace=True)
                    
                    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                    df['ticker'] = ticker
                    return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
                else:
                    return pd.DataFrame() 

        except requests.exceptions.RequestException:
            time.sleep(5)
        except Exception:
            return pd.DataFrame() 
        
    return pd.DataFrame()