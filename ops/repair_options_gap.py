import sys
import duckdb
import pandas as pd
import requests
import time
import math
import yfinance as yf
from datetime import datetime, timedelta, date
from pathlib import Path

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SurgicalRepair")

# ⚡ TARGET PARAMETERS
START_DATE = "2025-12-09"
END_DATE = "2025-12-17"
CONTEXT_TICKER = "SPY"  # Proxy for XSP range
BUFFER_STRIKES = 2      # M27 Protocol: Low-2 to High+2
API_KEY = config.POLYGON_API_KEY

# ==============================================================================
# 2. BATTLEFIELD DEFINITION (Context)
# ==============================================================================
def get_surgical_range(target_date_str):
    """
    Fetches SPY High/Low for the day to define the 'Kill Box'.
    Uses Yahoo Finance for robust context data (free).
    """
    try:
        dt = datetime.strptime(target_date_str, '%Y-%m-%d')
        # Fetch 1 day of data
        df = yf.download(CONTEXT_TICKER, start=dt, end=dt + timedelta(days=1), progress=False, auto_adjust=True)
        
        if df.empty:
            log.warning(f"⚠️ No Context Data for {target_date_str}")
            return None, None
            
        # Handle MultiIndex headers if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        high = float(df['High'].iloc[0])
        low = float(df['Low'].iloc[0])
        
        return high, low
    except Exception as e:
        log.error(f"Context Error: {e}")
        return None, None

def generate_tickers(target_date_str, high, low):
    """Generates the full list of contracts for the identified range."""
    # XSP trades roughly at SPY price level
    strike_min = math.floor(low) - BUFFER_STRIKES
    strike_max = math.ceil(high) + BUFFER_STRIKES
    
    dt = datetime.strptime(target_date_str, '%Y-%m-%d')
    fmt_date = dt.strftime('%y%m%d')
    
    tickers = []
    # Generate Calls AND Puts for every strike in range
    for k in range(strike_min, strike_max + 1):
        strike_fmt = f"{k * 1000:08d}"
        tickers.append(f"O:XSP{fmt_date}C{strike_fmt}")
        tickers.append(f"O:XSP{fmt_date}P{strike_fmt}")
        
    return tickers, strike_min, strike_max

# ==============================================================================
# 3. INGESTION ENGINE
# ==============================================================================
def fetch_polygon_1m(ticker, date_str):
    """Downloads 1-minute bars from Polygon."""
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {"adjusted": "true", "limit": 50000, "apiKey": API_KEY}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code == 429:
            log.warning("   🛑 Rate Limit! Pausing 65s...")
            time.sleep(65)
            return fetch_polygon_1m(ticker, date_str) # Retry
            
        if r.status_code == 200:
            data = r.json()
            if data.get('resultsCount', 0) > 0:
                df = pd.DataFrame(data['results'])
                # Normalize Schema
                df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                df['ticker'] = ticker.replace("O:", "")
                
                # Parse Metadata
                # O:XSP251209C00590000
                df['expiration'] = datetime.strptime(date_str, '%Y-%m-%d').date()
                df['type'] = 'C' if 'C0' in ticker else 'P'
                # Extract Strike from end
                strike_raw = ticker[-8:]
                df['strike'] = float(strike_raw) / 1000.0
                
                return df[['datetime_utc', 'ticker', 'expiration', 'strike', 'type', 'open', 'high', 'low', 'close', 'volume']]
                
    except Exception as e:
        log.error(f"   ❌ Net Error: {e}")
        
    return pd.DataFrame()

# ==============================================================================
# 4. MISSION EXECUTION
# ==============================================================================
def run_surgical_repair():
    if not config.DB_FILE.exists():
        log.error("Vault not found.")
        return

    log.info(f"🚑 STARTING SURGICAL REPAIR: {START_DATE} -> {END_DATE}")
    log.info(f"📋 Protocol M27: Range [Low-{BUFFER_STRIKES}] to [High+{BUFFER_STRIKES}]")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # Generate Date List
    s_dt = datetime.strptime(START_DATE, '%Y-%m-%d')
    e_dt = datetime.strptime(END_DATE, '%Y-%m-%d')
    delta = e_dt - s_dt
    
    for i in range(delta.days + 1):
        day = s_dt + timedelta(days=i)
        d_str = day.strftime('%Y-%m-%d')
        
        # Skip Weekends
        if day.weekday() > 4: continue
        
        print(f"\n📅 PROCESSING: {d_str}")
        
        # 1. DEFINE BATTLEFIELD
        high, low = get_surgical_range(d_str)
        if not high: continue
        
        target_tickers, s_min, s_max = generate_tickers(d_str, high, low)
        log.info(f"   🎯 Range: {s_min}-{s_max} | Contracts: {len(target_tickers)}")
        
        # 2. EXECUTE DOWNLOADS
        day_saved = 0
        for idx, ticker in enumerate(target_tickers):
            # Clean ticker for DB check
            clean_ticker = ticker.replace("O:", "")
            
            # Check if exists
            exists = con.execute(f"SELECT COUNT(*) FROM {config.TBL_OPTIONS} WHERE ticker='{clean_ticker}'").fetchone()[0]
            if exists > 10:
                print(f"   [{idx+1}/{len(target_tickers)}] ⏭️  Skipping {clean_ticker} (Data Exists)", end='\r')
                continue
                
            print(f"   [{idx+1}/{len(target_tickers)}] ⬇️  Downloading {clean_ticker}...", end='\r')
            
            df = fetch_polygon_1m(ticker, d_str)
            
            if not df.empty:
                con.register('df_temp', df)
                con.execute(f"""
                    INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
                    (datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume)
                    SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume 
                    FROM df_temp
                """)
                con.unregister('df_temp')
                day_saved += len(df)
                
                # FREE TIER PACING (5 calls/min = 12s sleep)
                time.sleep(13)
            else:
                # Small sleep on empty/fail to be safe
                time.sleep(1)
                
        if day_saved > 0:
            log.info(f"\n   ✅ SAVED: {day_saved} rows for {d_str}")
        else:
            log.info(f"\n   ℹ️  No new data needed for {d_str}")

    con.close()
    log.info("\n🎉 REPAIR OPERATION COMPLETE.")

if __name__ == "__main__":
    run_surgical_repair()