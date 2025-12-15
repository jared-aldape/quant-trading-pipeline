import sys
import duckdb
import pandas as pd
import numpy as np
from scipy.stats import norm
from pathlib import Path
from datetime import datetime
import warnings
import re # Added for regex parsing

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
    # Prevent division by zero if T is 0 (expiration)
    T = np.maximum(T, 1e-9)
    sigma = np.maximum(sigma, 1e-9)
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    pdf_d1 = norm.pdf(d1)
    cdf_d1 = norm.cdf(d1)
    cdf_d2 = norm.cdf(d2)
    
    # Initialize Arrays
    delta = np.zeros(len(df))
    gamma = np.zeros(len(df))
    vega  = np.zeros(len(df))
    theta = np.zeros(len(df))
    
    # --- CALLS ---
    call_mask = (df['type'] == 'C').values
    if np.any(call_mask):
        delta[call_mask] = cdf_d1[call_mask]
        theta[call_mask] = (- (S[call_mask] * pdf_d1[call_mask] * sigma[call_mask]) / (2 * np.sqrt(T[call_mask])) 
                            - r[call_mask] * K[call_mask] * np.exp(-r[call_mask] * T[call_mask]) * norm.cdf(d2[call_mask]))

    # --- PUTS ---
    put_mask = (df['type'] == 'P').values
    if np.any(put_mask):
        delta[put_mask] = cdf_d1[put_mask] - 1
        theta[put_mask] = (- (S[put_mask] * pdf_d1[put_mask] * sigma[put_mask]) / (2 * np.sqrt(T[put_mask])) 
                           + r[put_mask] * K[put_mask] * np.exp(-r[put_mask] * T[put_mask]) * norm.cdf(-d2[put_mask]))

    # --- SHARED ---
    gamma = pdf_d1 / (S * sigma * np.sqrt(T))
    vega = S * pdf_d1 * np.sqrt(T) / 100  # Divide by 100 for standard % change interpretation
    
    # Assign back
    df['delta'] = delta
    df['gamma'] = gamma
    df['vega'] = vega
    df['theta'] = theta / 365 # Annualized theta to daily decay estimate
    
    return df

# ==============================================================================
# 3. WORKFLOW LOGIC
# ==============================================================================
def calculate_and_fill_greeks():
    """
    Scans the Option Vault for rows with missing Greeks and backfills them.
    This is the entry point for the Daily Harvest pipeline.
    """
    if not config.DB_FILE.exists():
        log.error("❌ Database not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Find rows needing calculation (Limit batch size for safety)
    # Fetching 'close' as proxy for underlying price if we don't have spot index joined yet
    # Ideally, we should join with indices_1m, but for approximation, we assume
    # we need to fetch the underlying price separately or pass it.
    # CRITICAL: We need Underlying Price (SPX) to calc Greeks.
    
    # Let's fetch pending options + join with SPX index on timestamp
    q_fetch = f"""
        SELECT 
            o.datetime_utc, 
            o.ticker, 
            o.close as opt_price,
            i.close as underlying_price
        FROM {config.TBL_OPTIONS} o
        LEFT JOIN {config.TBL_INDICES} i 
            ON o.datetime_utc = i.datetime_utc AND i.ticker = 'SPX'
        WHERE o.delta IS NULL
        -- AND i.close IS NOT NULL -- Only calc where we have SPX data
        ORDER BY o.datetime_utc DESC
        LIMIT 50000 
    """
    try:
        df = con.execute(q_fetch).df()
    except Exception as e:
        log.warning(f"Greek Fetch Error (Table might not exist yet): {e}")
        con.close()
        return
    
    if df.empty:
        log.info("✅ No pending Greek calculations found.")
        con.close()
        return

    # Check for missing underlying data
    missing_spx = df[df['underlying_price'].isna()]
    if not missing_spx.empty:
        log.warning(f"⚠️ {len(missing_spx)} option rows missing matching SPX index data. Greeks skipped for these.")
        df = df.dropna(subset=['underlying_price'])
        if df.empty:
            con.close()
            return

    log.info(f"🧮 Calculating Greeks for {len(df)} new rows...")
    
    # 2. Enrich Data (Parse Ticker for Strike/Exp)
    # Ticker format expected: SPX231215C04500000
    # We need to extract Date, Type, Strike
    
    def parse_meta(ticker):
        # Regex for standard Polygon/OPRA format
        # Matches: [Root][YYMMDD][C/P][Strike * 1000]
        match = re.search(r'([A-Z]+)(\d{6})([CP])(\d{8})', ticker)
        if match:
            # root = match.group(1) # Unused here
            date_str = match.group(2)
            type_char = match.group(3)
            strike_str = match.group(4)
            
            # Expiration
            exp_date = pd.to_datetime(date_str, format='%y%m%d')
            # Strike (divide by 1000)
            strike = float(strike_str) / 1000.0
            
            return exp_date, type_char, strike
        return None, None, None

    # Apply Parsing
    meta_data = df['ticker'].apply(parse_meta)
    df['expiration'] = [x[0] for x in meta_data]
    df['type'] = [x[1] for x in meta_data]
    df['strike'] = [x[2] for x in meta_data]
    
    # Filter out parse failures
    df = df.dropna(subset=['expiration'])
    
    # Calculate Time to Expiry (Annualized)
    # Add 16 hours (4pm close) to exp date for accuracy? Standard is 4pm EST.
    df['time_to_expiry'] = (df['expiration'] + pd.Timedelta(hours=16) - df['datetime_utc']).dt.total_seconds() / (365 * 24 * 3600)
    
    # Defaults
    df['risk_free_rate'] = 0.045 # 4.5% static for now, or fetch from DB
    df['iv'] = 0.20 # 20% fallback if not calculating IV implies
    
    # 3. Calculate
    df_calc = calculate_greeks_vectorized(df)
    
    # 4. Update DB
    # We use a temporary table to bulk update
    con.register('greek_updates', df_calc[['datetime_utc', 'ticker', 'delta', 'gamma', 'vega', 'theta']])
    
    update_q = f"""
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
    con.execute(update_q)
    log.info(f"✅ Greeks committed to Vault.")
    con.close()