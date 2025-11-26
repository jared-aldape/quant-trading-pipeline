import sys
import os
import duckdb
import pandas as pd
import numpy as np
from scipy.stats import norm
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

log = get_logger("GreekCalculator")

def black_scholes_call(S, K, T, r, sigma):
    if sigma <= 0 or T <= 0: return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

def calculate_iv_newton(price, S, K, T, r):
    """
    Newton-Raphson method to imply volatility from price.
    """
    sigma = 0.5
    for i in range(10):
        price_est = black_scholes_call(S, K, T, r, sigma)
        diff = price - price_est
        if abs(diff) < 1e-4: return sigma
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T)
        if vega == 0: break
        sigma = sigma + diff / vega
    return sigma

def calculate_greeks(row):
    try:
        S = row['spx_price'] / 10.0
        K = row['strike']
        r = row['risk_free_rate']
        
        # 1. Handle Current Time (Ensure UTC)
        # We explicitly convert to UTC to match the Timezone Law
        if row['datetime_utc'].tz is None:
            current_dt = row['datetime_utc'].tz_localize(config.TZ_UTC)
        else:
            current_dt = row['datetime_utc'].tz_convert(config.TZ_UTC)
            
        # 2. Handle Expiry Time (DST-Aware Fix)
        # Logic: Expiration is always 4:00 PM ET (16:00).
        # We localize to NY first to let Pandas handle the DST offset (UTC-4 vs UTC-5)
        exp_date = pd.to_datetime(row['expiration'])
        exp_ny = exp_date.tz_localize(config.TZ_NY) + pd.Timedelta(hours=16)
        
        # Then convert to UTC for the "Time to Expiry" math
        exp_dt = exp_ny.tz_convert(config.TZ_UTC)
        
        # Calculate Time to Expiry (in Years)
        T = (exp_dt - current_dt).total_seconds() / (3600 * 24 * 365)
        
        if T <= 0.001: return pd.Series([None]*5)

        price = row['close']

        iv = calculate_iv_newton(price, S, K, T, r)
        
        d1 = (np.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * np.sqrt(T))
        d2 = d1 - iv * np.sqrt(T)
        
        delta = norm.cdf(d1)
        gamma = norm.pdf(d1) / (S * iv * np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T) / 100 
        theta = (- (S * norm.pdf(d1) * iv) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365

        return pd.Series([iv, delta, gamma, vega, theta])
    except Exception as e:
        return pd.Series([None]*5)

def run_greek_calculation():
    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    log.info("📥 Loading Data (Options + SPX + IRX)...")
    
    # 1. CREATE IRX VIEW
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW v_rates AS 
        SELECT date, rate/100.0 as rate_decimal FROM {config.TBL_IRX}
    """)
    
    # 2. QUERY JOIN
    # Ensure SPX and Option times are aligned
    query = f"""
    SELECT 
        o.datetime_utc,
        o.ticker,
        o.strike,
        o.expiration,
        o.close,
        i.close as spx_price,
        r.rate_decimal as risk_free_rate
    FROM {config.TBL_OPTIONS} o
    ASOF JOIN (SELECT datetime_utc, close FROM {config.TBL_INDICES} WHERE ticker='SPX') i
        ON o.datetime_utc >= i.datetime_utc
    LEFT JOIN v_rates r
        ON CAST(o.datetime_utc AS DATE) = r.date
    WHERE o.iv IS NULL
    """
    
    try:
        df = con.execute(query).df()
    except Exception as e:
        log.error(f"❌ Query Failed: {e}")
        return

    if df.empty:
        log.info("✅ No options need Greek calculation.")
        return

    # Handle missing IRX rates (Fallback to 4.5%)
    missing_rates = df['risk_free_rate'].isna().sum()
    if missing_rates > 0:
        log.warning(f"⚠️ {missing_rates} rows missing IRX rate. Using 4.5% fallback.")
        df['risk_free_rate'] = df['risk_free_rate'].fillna(0.045)

    log.info(f"🧮 Calculating Greeks for {len(df)} rows...")
    
    # Ensure correct types for Pandas apply
    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
    df['expiration'] = pd.to_datetime(df['expiration'])
    
    greeks = df.apply(calculate_greeks, axis=1)
    greeks.columns = ['iv', 'delta', 'gamma', 'vega', 'theta']
    
    result = pd.concat([df[['datetime_utc', 'ticker']], greeks], axis=1)
    
    log.info("💾 Saving Greeks to Database...")
    con.register('greeks_source', result)
    
    # Update back to the table
    update_q = f"""
    UPDATE {config.TBL_OPTIONS}
    SET 
        iv = g.iv,
        delta = g.delta,
        gamma = g.gamma,
        vega = g.vega,
        theta = g.theta
    FROM greeks_source g
    WHERE {config.TBL_OPTIONS}.datetime_utc = g.datetime_utc
      AND {config.TBL_OPTIONS}.ticker = g.ticker
    """
    
    con.execute(update_q)
    con.close()
    log.info("✅ Greek Calculation Complete.")

if __name__ == "__main__":
    run_greek_calculation()