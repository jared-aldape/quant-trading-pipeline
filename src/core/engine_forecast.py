import yfinance as yf
import pandas as pd
import numpy as np
import math
import pytz
from datetime import datetime, timedelta
from src.utils import config

# ==============================================================================
# PREDICTIVE CORE
# ==============================================================================

def fetch_market_data(ticker="SPY", period="5d", interval="5m"):
    """Fetches intraday data for analysis."""
    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
        if data.empty: return pd.DataFrame()
        
        data = data.reset_index()
        data.columns = [c.lower() for c in data.columns]
        
        # 1. Normalize to UTC Awareness First
        if data['datetime'].dt.tz is None:
            data['datetime'] = data['datetime'].dt.tz_localize('UTC')
        else:
            data['datetime'] = data['datetime'].dt.tz_convert('UTC')
            
        return data
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return pd.DataFrame()

def apply_timezone_law(df):
    """Converts a DataFrame's 'datetime' column to Project Local Time (PST)."""
    if df.empty or 'datetime' not in df.columns: return df
    
    # Convert from whatever it is (usually UTC/NY) to Config Local (PST)
    df['datetime'] = df['datetime'].dt.tz_convert(config.TZ_LOCAL)
    return df

def generate_linear_regression(ticker="SPY"):
    """
    Generates a 2-Standard Deviation Linear Regression Channel.
    """
    df = fetch_market_data(ticker, period="5d", interval="1h") # Use 1h for trend stability
    if df.empty: return {"status": "ERROR", "msg": "No Data"}

    # Calculations usually need NY time logic, but for pure LinReg plotting,
    # we can just use the raw data.
    
    # Prepare X (Ordinal Time) and Y (Price)
    df['x'] = np.arange(len(df))
    y = df['close'].values
    x = df['x'].values

    # Calculate Linear Regression (y = mx + b)
    slope, intercept = np.polyfit(x, y, 1)
    df['reg_line'] = slope * x + intercept

    # Calculate Standard Deviation (Volatility)
    residuals = y - df['reg_line']
    std_dev = np.std(residuals)
    
    # Calculate Channel Bands (2 Sigma)
    df['upper_band'] = df['reg_line'] + (2 * std_dev)
    df['lower_band'] = df['reg_line'] - (2 * std_dev)

    # Project to Current Price
    current_idx = len(df) - 1
    proj_high = df.iloc[current_idx]['upper_band']
    proj_low = df.iloc[current_idx]['lower_band']
    current_price = df.iloc[current_idx]['close']

    # Determine Trend
    if slope > 0:
        trend = "BULLISH TREND (Rising Channel)"
    else:
        trend = "BEARISH TREND (Falling Channel)"

    # --- TIMEZONE LAW ENFORCEMENT ---
    df = apply_timezone_law(df)

    return {
        "status": "ACTIVE",
        "type": "LIN",
        "ticker": ticker,
        "current_price": current_price,
        "orb_high": df.iloc[current_idx]['reg_line'], # Use Reg Line as Midpoint
        "orb_low": df.iloc[current_idx]['reg_line'],
        "proj_high": proj_high,
        "proj_low": proj_low,
        "trend": trend,
        "dataframe": df,
        "slope": slope
    }

def generate_forecast(ticker="SPY", model_type="ORB"):
    """
    Router for different forecast models.
    """
    if model_type == "LIN":
        return generate_linear_regression(ticker)
    
    # Default: ORB Model
    df = fetch_market_data(ticker, period="5d", interval="5m")
    if df.empty: return {"status": "ERROR", "msg": "Failed to fetch historical data."}

    # 1. Identify Today's Session (Needs NY Time for Logic)
    df_ny = df.copy()
    df_ny['datetime'] = df_ny['datetime'].dt.tz_convert('America/New_York')
    
    now_ny = datetime.now(pytz.timezone('America/New_York'))
    today = now_ny.date()
    today_df = df_ny[df_ny['datetime'].dt.date == today].copy()
    
    if len(today_df) < 6:
        return {"status": "WAITING", "msg": "Insufficient data (Need 30+ minutes of candles)"}

    # 2. Calculate Opening Range (First 60 Mins)
    open_time = today_df.iloc[0]['datetime']
    orb_end_time = open_time + timedelta(minutes=60)
    orb_df = today_df[today_df['datetime'] <= orb_end_time]
    
    if orb_df.empty: 
        return {"status": "WAITING", "msg": "ORB not yet calculated (Wait for 10:30 AM EST)"}

    orb_high = orb_df['high'].max()
    orb_low = orb_df['low'].min()
    orb_range = orb_high - orb_low
    current_price = today_df.iloc[-1]['close']

    # 3. Project Targets (1.0x Expansion)
    proj_high = orb_high + orb_range
    proj_low = orb_low - orb_range
    
    # 4. Trend Bias
    if current_price > orb_high:
        trend = "BULLISH (Breakout)"
    elif current_price < orb_low:
        trend = "BEARISH (Breakdown)"
    else:
        trend = "NEUTRAL (Chopping inside ORB)"

    # --- TIMEZONE LAW ENFORCEMENT ---
    # Convert the slice back to Local (PST) for display
    today_df = apply_timezone_law(today_df)

    return {
        "status": "ACTIVE",
        "type": "ORB",
        "ticker": ticker,
        "current_price": current_price,
        "orb_high": orb_high,
        "orb_low": orb_low,
        "proj_high": proj_high,
        "proj_low": proj_low,
        "trend": trend,
        "dataframe": today_df
    }