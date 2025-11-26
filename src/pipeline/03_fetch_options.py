import sys
import os
import requests
import pandas as pd
import duckdb
import time
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# We are in: quant-trading-pipeline/src/pipeline/
# We need to reach: quant-trading-pipeline/ (Root)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Add Root to System Path to allow imports from 'src.utils'
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OptionFetcher")

# Configuration
STRIKE_RANGE = 2  
CONTRACT_TYPE = 'C'
API_PACE_SECONDS = 12.5 

DB_SCHEMA_ORDER = [
    'datetime_utc', 'ticker', 'expiration', 'strike', 'type',
    'open', 'high', 'low', 'close', 'volume',
    'iv', 'delta', 'gamma', 'vega', 'theta'
]

def get_progress_bar(current, total, length=20):
    """Generates a text-based progress bar string."""
    percent = float(current) / total
    arrow = '█' * int(round(percent * length))
    spaces = '-' * (length - len(arrow))
    return f"[{arrow}{spaces}] {int(percent * 100)}%"

def get_polygon_data(ticker, date_str):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": config.POLYGON_API_KEY
    }
    
    try:
        r = requests.get(url, params=params)
        if r.status_code == 429:
            log.warning("⏳ 429 Rate Limit Hit. Pausing 65s to reset...")
            time.sleep(65)
            return get_polygon_data(ticker, date_str)
            
        data = r.json()
        if data.get('status') != 'OK' or not data.get('results'):
            return pd.DataFrame()
            
        df = pd.DataFrame(data['results'])
        df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
        
        # --- TIMEZONE TRANSFORMATION: ENFORCING THE TIMEZONE LAW ---
        # 1. Convert UNIX ms to Datetime Object (Explicitly UTC)
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms', utc=True)
        
        # 2. Safety Check: If for any reason it's naive (e.g. source change), Localize from NY.
        if df['datetime_utc'].dt.tz is None:
             df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_NY)
        
        # 3. Final Conversion to Vault Standard (UTC)
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)

        df['ticker'] = ticker
        return df
        
    except Exception as e:
        log.error(f"❌ API Error for {ticker}: {e}")
        return pd.DataFrame()

def generate_option_ticker(root, date_obj, strike, type='C'):
    yymmdd = date_obj.strftime('%y%m%d')
    strike_scaled = int(strike * 1000)
    strike_str = f"{strike_scaled:08d}"
    return f"O:{root}{yymmdd}{type}{strike_str}"

def get_underlying_price(con, signal_ts):
    ts_min = signal_ts.timestamp() - 3600
    ts_max = signal_ts.timestamp() + 3600
    
    # 1. Try SPX
    spx_query = f"""
    SELECT close FROM {config.TBL_INDICES} 
    WHERE ticker = 'SPX' AND datetime_utc BETWEEN to_timestamp({ts_min}) AND to_timestamp({ts_max})
    ORDER BY ABS(EPOCH(datetime_utc) - {signal_ts.timestamp()}) ASC LIMIT 1
    """
    price_row = con.execute(spx_query).fetchone()
    if price_row: return price_row[0], "SPX"
        
    # 2. Try Futures (ES)
    es_query = f"""
    SELECT close FROM {config.TBL_FUTURES} 
    WHERE ticker = 'ES' AND datetime_utc BETWEEN to_timestamp({ts_min}) AND to_timestamp({ts_max})
    ORDER BY ABS(EPOCH(datetime_utc) - {signal_ts.timestamp()}) ASC LIMIT 1
    """
    price_row = con.execute(es_query).fetchone()
    if price_row: return price_row[0], "ES (Futures)"
        
    return None, None

def fetch_options():
    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    signals = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC").df()
    total_signals = len(signals)
    log.info(f"📋 Found {total_signals} signals to process.")
    
    total_rows_inserted = 0
    
    for i, (index, row) in enumerate(signals.iterrows()):
        # --- PROGRESS BAR ---
        progress_str = get_progress_bar(i + 1, total_signals)
        
        signal_ts = pd.to_datetime(row['entry_timestamp_utc'], unit='ms', utc=True)
        trade_date = signal_ts.date()
        trade_date_str = str(trade_date)
        
        # Hybrid Price Lookup
        price, source = get_underlying_price(con, signal_ts)
        
        if price is None:
            continue
            
        xsp_price = price / 10.0
        atm_strike = round(xsp_price)
        
        # Update Manifest
        con.execute(f"UPDATE {config.TBL_MANIFEST} SET xsp_price = {xsp_price} WHERE entry_timestamp_utc = {row['entry_timestamp_utc']}")
        
        log.info(f"{progress_str} | Processing {trade_date_str} | Source: {source} | ATM: {atm_strike}")
        
        strikes_to_fetch = range(atm_strike - STRIKE_RANGE, atm_strike + STRIKE_RANGE + 1)
        
        for k in strikes_to_fetch:
            ticker = generate_option_ticker("XSP", trade_date, k, CONTRACT_TYPE)
            
            # Check DB first (Fast Skip)
            exists = con.execute(f"SELECT count(*) FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}'").fetchone()[0]
            
            if exists > 0:
                continue 

            # API Call
            df = get_polygon_data(ticker, trade_date_str)
            
            if not df.empty:
                df['expiration'] = trade_date
                df['strike'] = float(k)
                df['type'] = CONTRACT_TYPE
                for col in ['iv', 'delta', 'gamma', 'vega', 'theta']: df[col] = None
                
                df = df[DB_SCHEMA_ORDER]
                
                try:
                    con.register('df_opt', df)
                    con.execute(f"""
                    INSERT INTO {config.TBL_OPTIONS} SELECT * FROM df_opt
                    ON CONFLICT (datetime_utc, ticker) DO NOTHING
                    """)
                    total_rows_inserted += len(df)
                    log.info(f"      -> Fetched {ticker}: {len(df)} rows")
                except Exception as e:
                    log.error(f"      ❌ DB Insert Error: {e}")
            
            # Pace API calls
            time.sleep(API_PACE_SECONDS)
            
    con.close()
    log.info(f"🏁 Option Fetch Complete. Total Rows Inserted: {total_rows_inserted}")

if __name__ == "__main__":
    fetch_options()