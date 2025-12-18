import yfinance as yf
import pandas as pd
import numpy as np
import time
import pytz
from datetime import datetime, timedelta
from src.utils import config

# ==============================================================================
# PREDICTIVE CORE
# ==============================================================================

def fetch_market_data(ticker="SPY", period="5d", interval="5m"):
    """
    Fetches intraday data with retry logic to prevent 'Ghost Data' or timeouts.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # ⚡ RETRY LOGIC: Yahoo API can be flaky
            data = yf.Ticker(ticker).history(period=period, interval=interval)
            
            if data.empty:
                time.sleep(1)
                continue
            
            data = data.reset_index()
            data.columns = [c.lower() for c in data.columns]
            
            # 1. Normalize to UTC Awareness First
            if data['datetime'].dt.tz is None:
                data['datetime'] = data['datetime'].dt.tz_localize('UTC')
            else:
                data['datetime'] = data['datetime'].dt.tz_convert('UTC')
                
            return data
            
        except Exception as e:
            print(f"Data Fetch Warning (Attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(1.5)
            
    return pd.DataFrame()

def apply_timezone_law(df):
    """Converts a DataFrame's 'datetime' column to Project Local Time (PST)."""
    if df.empty or 'datetime' not in df.columns: return df
    
    # Convert from whatever it is (usually UTC/NY) to Config Local (PST)
    df['datetime'] = df['datetime'].dt.tz_convert(config.TZ_LOCAL).dt.tz_localize(None)
    return df

def generate_forecast(ticker="SPY"):
    """
    Generates the ORB (Opening Range Breakout) Levels and Trend Bias.
    Used by Live Scope to project 'Ghost Lines' for support/resistance.
    """
    # 1. Get Data
    df = fetch_market_data(ticker, period="2d", interval="5m")
    df = apply_timezone_law(df)
    
    if df.empty:
        return {"status": "OFFLINE", "msg": "No Data Feed"}

    # 2. Filter for TODAY ONLY
    current_date = datetime.now(config.TZ_LOCAL).date()
    today_df = df[df['datetime'].dt.date == current_date].copy()
    
    if len(today_df) < 6:
        return {"status": "WAITING", "msg": "Building Market Data..."}

    # 3. Calculate Opening Range (Dynamic from Config)
    # Uses config.ORB_WINDOW_MINUTES (default 30)
    orb_minutes = getattr(config, 'ORB_WINDOW_MINUTES', 30)
    
    open_time = today_df.iloc[0]['datetime']
    orb_end_time = open_time + timedelta(minutes=orb_minutes)
    
    orb_df = today_df[today_df['datetime'] <= orb_end_time]
    
    if orb_df.empty: 
        return {"status": "WAITING", "msg": f"Wait for ORB ({orb_end_time.strftime('%H:%M')})"}

    orb_high = orb_df['high'].max()
    orb_low = orb_df['low'].min()
    orb_range = orb_high - orb_low
    current_price = today_df.iloc[-1]['close']

    # 4. Project Targets (Fibonacci-style Expansions)
    proj_high = orb_high + orb_range      # 100% Extension
    proj_low = orb_low - orb_range        # 100% Extension
    
    # 5. Trend Bias
    if current_price > orb_high:
        trend = "BULLISH"
        color = "#00bc8c" # Success Green
    elif current_price < orb_low:
        trend = "BEARISH"
        color = "#e74c3c" # Danger Red
    else:
        trend = "NEUTRAL"
        color = "#f39c12" # Warning Orange

    return {
        "status": "ACTIVE",
        "trend": trend,
        "color": color,
        "orb_h": orb_high,
        "orb_l": orb_low,
        "proj_h": proj_high,
        "proj_l": proj_low,
        "price": current_price,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }