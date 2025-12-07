import sys
import duckdb
import pandas as pd
import numpy as np
from scipy.stats import norm
from pathlib import Path
from datetime import datetime
import warnings

# Suppress divide by zero warnings in BS model
warnings.filterwarnings("ignore")

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: src/core/engine_greeks.py
# Root: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("GreekEngine")

# ==============================================================================
# 2. MATH MODELS (Vectorized Black-Scholes)
# ==============================================================================
def calculate_greeks_vectorized(df):
    """
    Calculates Delta, Gamma, Vega, Theta using Vectorized Numpy (Fast).
    Input DF must have: underlying_price, strike, time_to_expiry, risk_free_rate, iv, type ('C'/'P')
    """
    if df.empty: return df

    S = df['underlying_price'].values
    K = df['strike'].values
    T = df['time_to_expiry'].values
    r = df['risk_free_rate'].values
    sigma = df['iv'].values
    
    # Pre-calculate d1 and d2
    # Avoid divide by zero for 0DTE (T < 0.0001)
    T = np.maximum(T, 0.00001) 
    
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Standard Normal PDF/CDF
    pdf_d1 = norm.pdf(d1)
    cdf_d1 = norm.cdf(d1)
    cdf_d2 = norm.cdf(d2)
    cdf_neg_d1 = norm.cdf(-d1)
    cdf_neg_d2 = norm.cdf(-d2)

    # CALLS
    call_mask = (df['type'] == 'C')
    
    # PUTS
    put_mask = (df['type'] == 'P')

    # --- DELTA ---
    delta = np.zeros(len(df))
    delta[call_mask] = cdf_d1[call_mask]
    delta[put_mask] = cdf_d1[put_mask] - 1.0
    
    # --- GAMMA (Same for Call/Put) ---
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    
    # --- VEGA (Same for Call/Put) ---
    # Vega is usually expressed per 1% change in vol, so / 100
    vega = (S * pdf_d1 * sqrt_T) / 100.0
    
    # --- THETA ---
    theta = np.zeros(len(df))
    term1 = -(S * pdf_d1 * sigma) / (2 * sqrt_T)
    
    # Call Theta
    theta[call_mask] = term1[call_mask] - (r[call_mask] * K[call_mask] * np.exp(-r[call_mask] * T[call_mask]) * cdf_d2[call_mask])
    # Put Theta
    theta[put_mask] = term1[put_mask] + (r[put_mask] * K[put_mask] * np.exp(-r[put_mask] * T[put_mask]) * cdf_neg_d2[put_mask])
    
    # Annualized to Daily
    theta = theta / 365.0

    # Assign back
    df['delta'] = delta
    df['gamma'] = gamma
    df['vega'] = vega
    df['theta'] = theta
    
    return df

# ==============================================================================
# 3. AGGREGATION ENGINE (Gamma Gravity)
# ==============================================================================
def calculate_net_gamma_exposure(con):
    """
    Calculates Volume-Weighted Gamma (VWG) to identify Sticky Levels.
    Returns a DataFrame of [strike, net_gamma_pressure]
    """
    try:
        # We use Volume as a proxy for Hedging Activity (Flow)
        query = f"""
        SELECT 
            strike,
            SUM(CASE WHEN type='C' THEN gamma * volume ELSE 0 END) as call_gamma_flow,
            SUM(CASE WHEN type='P' THEN gamma * volume * -1 ELSE 0 END) as put_gamma_flow,
            (SUM(CASE WHEN type='C' THEN gamma * volume ELSE 0 END) + 
             SUM(CASE WHEN type='P' THEN gamma * volume * -1 ELSE 0 END)) as net_gamma_flow
        FROM {config.TBL_OPTIONS}
        WHERE datetime_utc >= (SELECT MAX(datetime_utc) - INTERVAL 1 DAY FROM {config.TBL_OPTIONS})
        GROUP BY strike
        ORDER BY strike ASC
        """
        df = con.execute(query).df()
        return df
    except Exception as e:
        log.error(f"GEX Calc Failed: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. EXECUTION PIPELINE
# ==============================================================================
def run_greek_calculation():
    log.info("🧮 Starting Greek Calculation Cycle...")
    
    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # 1. Fetch Option Data needing Greeks
        # CRITICAL FIX: ASOF JOIN requires an Inequality (>=) to define "closest previous match"
        query = f"""
        SELECT 
            o.datetime_utc, o.ticker, o.expiration, o.strike, o.type, o.close as opt_price, o.iv,
            i.close as underlying_price,
            r.rate as risk_free_rate
        FROM {config.TBL_OPTIONS} o
        ASOF JOIN {config.TBL_INDICES} i 
            ON i.ticker = 'SPX' AND o.datetime_utc >= i.datetime_utc
        LEFT JOIN {config.TBL_IRX} r 
            ON CAST(o.datetime_utc AS DATE) = r.date
        WHERE o.delta IS NULL OR o.delta = 0
        """
        
        df = con.execute(query).df()
        
        if df.empty:
            log.info("✅ No pending contracts for Greek calculation.")
            con.close()
            return

        log.info(f"⚡ Calculating Greeks for {len(df)} records...")

        # 2. Pre-Process
        # Convert timezone-aware datetimes to UTC-naive if necessary for math
        now_utc = pd.Timestamp.utcnow()
        df['expiration'] = pd.to_datetime(df['expiration']).dt.tz_localize('UTC') if df['expiration'].dtype == 'O' else df['expiration']
        
        # Calculate T (Time to Expiry in Years)
        # We use a small epsilon for 0DTE to avoid division by zero
        seconds_to_exp = (df['expiration'] + pd.Timedelta(hours=16) - df['datetime_utc']).dt.total_seconds()
        df['time_to_expiry'] = seconds_to_exp / (365 * 24 * 3600)
        
        # Fill Missing Risk Free Rate (Default 4.5%)
        df['risk_free_rate'] = df['risk_free_rate'].fillna(4.5) / 100.0
        
        # Fill Missing IV (Default 20%)
        df['iv'] = df['iv'].fillna(0.2)

        # 3. Vectorized Calculation
        df = calculate_greeks_vectorized(df)

        # 4. Batch Update (Using Temp Table for Speed)
        log.info("💾 Saving Greeks to Vault...")
        con.execute("CREATE TEMP TABLE greek_updates AS SELECT datetime_utc, ticker, delta, gamma, vega, theta FROM df")
        
        update_query = f"""
        UPDATE {config.TBL_OPTIONS}
        SET 
            delta = greek_updates.delta,
            gamma = greek_updates.gamma,
            vega = greek_updates.vega,
            theta = greek_updates.theta
        FROM greek_updates
        WHERE {config.TBL_OPTIONS}.datetime_utc = greek_updates.datetime_utc 
          AND {config.TBL_OPTIONS}.ticker = greek_updates.ticker
        """
        con.execute(update_query)
        con.execute("DROP TABLE greek_updates")
        
        log.info(f"✅ Updated {len(df)} records.")
        
        con.close()

    except Exception as e:
        log.error(f"Greek Engine Failed: {e}")

if __name__ == "__main__":
    run_greek_calculation()