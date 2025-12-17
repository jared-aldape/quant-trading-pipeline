import json
import os
import sys
import time as time_lib
from datetime import datetime, time, timedelta
import pytz
from pathlib import Path
import pandas as pd
import numpy as np
from scipy.stats import norm
import yfinance as yf
import duckdb

# ==============================================================================
# 1. PATH CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SimEngine")
SESSION_FILE = ROOT_DIR / "data" / "sim_session.json"
TBL_SIM_LOG = getattr(config, 'TBL_SIM_LOG', 'active_simulation_log')

DEFAULT_SESSION = {
    "balance": 2000.0,
    "liquid_cash": 2000.0,
    "positions": [],
    "trades": []
}

# ⚡ CACHE: Pre-seeded with a fallback price to prevent startup crashes
_MARKET_CACHE = {"price": 680.0, "vix": 0.15, "irx": 0.045, "last_update": 0}
MARKET_CACHE_DURATION = 15 # Seconds to wait between Yahoo calls

# ==============================================================================
# 2. SESSION MANAGEMENT
# ==============================================================================
def load_session():
    """Loads session safely. Creates one if missing."""
    if not SESSION_FILE.exists():
        save_session(DEFAULT_SESSION)
        return DEFAULT_SESSION
    try:
        with open(SESSION_FILE, 'r') as f:
            session = json.load(f)
            # Merge defaults in case of new fields
            for k, v in DEFAULT_SESSION.items():
                if k not in session: session[k] = v
            return session
    except:
        return DEFAULT_SESSION

def save_session(session):
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump(session, f, indent=4)
    except Exception as e:
        log.error(f"Session Save Error: {e}")

def reset_session():
    save_session(DEFAULT_SESSION)
    log.info("Session Reset")

def is_rth():
    """Checks if current time is within Regular Trading Hours (09:30 - 16:00 ET)."""
    tz_ny = pytz.timezone('America/New_York')
    now = datetime.now(tz_ny)
    
    if now.weekday() >= 5: return False
    
    current_time = now.time()
    market_open = time(9, 30)
    market_close = time(16, 0)
    
    return market_open <= current_time < market_close

# ==============================================================================
# 3. MARKET DATA (FAULT TOLERANT)
# ==============================================================================
def get_live_price(ticker="SPY"):
    """
    Fetches price with 'Cooldown on Failure' to stop log spam.
    """
    global _MARKET_CACHE
    
    # 1. Check Cache
    if time_lib.time() - _MARKET_CACHE['last_update'] < MARKET_CACHE_DURATION:
        return _MARKET_CACHE['price']

    try:
        # 2. Attempt Fetch
        price = yf.Ticker("SPY").fast_info.last_price
        
        # Sanity Check (SPY should be > 100)
        if price < 100: 
             spx = yf.Ticker("^GSPC").fast_info.last_price
             price = spx / 10.0

        if price and price > 0:
            _MARKET_CACHE['price'] = price
            _MARKET_CACHE['last_update'] = time_lib.time()
            return price
            
    except Exception as e:
        log.warning(f"Price Fetch Fail ({e}). Using Cache.")
        
    # 3. CRITICAL: Update timestamp even on failure. 
    # This forces the system to wait 15s before trying again, stopping the loop.
    _MARKET_CACHE['last_update'] = time_lib.time()
    return _MARKET_CACHE['price']

def get_market_context():
    global _MARKET_CACHE
    try:
        # Update rarely (every 60s)
        if time_lib.time() - _MARKET_CACHE.get('ctx_update', 0) > 60:
            vix = yf.Ticker("^VIX").fast_info.last_price
            irx = yf.Ticker("^IRX").fast_info.last_price
            if vix: _MARKET_CACHE['vix'] = vix / 100.0
            if irx: _MARKET_CACHE['irx'] = irx / 100.0
            _MARKET_CACHE['ctx_update'] = time_lib.time()
            
        return _MARKET_CACHE['irx'], _MARKET_CACHE['vix']
    except:
        return 0.045, 0.15

def get_time_to_close():
    ny_tz = pytz.timezone('America/New_York')
    now = datetime.now(ny_tz)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if now >= close: return 0.00001
    
    minutes_left = (close - now).total_seconds() / 60.0
    return minutes_left / (252 * 390) 

def black_scholes(S, K, T, r, sigma, type='Call'):
    if T <= 0: return max(0, S - K) if type == 'Call' else max(0, K - S)
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if type == 'Call' or type == 'CALL':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
    return max(0.01, price)

# ==============================================================================
# 4. EXECUTION LOGIC
# ==============================================================================
def preview_entry(qty, limit_px=None, offset=0):
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    offset = int(offset) if offset else 0
    atm_strike = round(price) + offset
    opt_price = black_scholes(price, atm_strike, T, r, sigma, 'Call')
    
    if limit_px and limit_px < opt_price: opt_price = limit_px 
    
    total = opt_price * 100 * qty
    return {'total_cost': total, 'est_fill': opt_price, 'strike_desc': f"{atm_strike}"}

def execute_entry(action, qty, order_type='MARKET', offset=0):
    if not is_rth(): return "MARKET CLOSED (RTH ONLY)"

    session = load_session()
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    offset = int(offset) if offset else 0
    atm_strike = round(price) + offset
    opt_type = 'Call' if action == 'CALL' else 'Put'
    
    opt_price = black_scholes(price, atm_strike, T, r, sigma, opt_type)
    cost = opt_price * 100 * qty
    
    if session['liquid_cash'] < cost: 
        return f"INSUFFICIENT FUNDS (Need ${cost:.2f})"
    
    session['liquid_cash'] -= cost
    entry_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    new_pos = {
        "id": f"SIM_{int(time_lib.time()*1000)}",
        "entry_time": entry_ts,
        "type": opt_type,
        "strike": atm_strike,
        "contracts": qty,
        "entry_px": opt_price,
        "ticker": f"XSP {opt_type} {atm_strike}",
        "cost_basis": cost
    }
    
    # ⚡ RECORD BUY TRANSACTION
    buy_log = {
        "exit_time": entry_ts,
        "ticker": new_pos['ticker'],
        "action": f"BUY {action}",
        "qty": qty,
        "entry_px": 0, 
        "price": opt_price,
        "pnl": 0.0,
        "reason": "OPEN"
    }
    
    session['trades'].append(buy_log)
    session['positions'].append(new_pos)
    save_session(session)
    return f"BOUGHT {qty}x {opt_type} @ ${opt_price:.2f}"

def execute_exit(trade_id):
    if not is_rth(): return "MARKET CLOSED"
    return close_position(trade_id)

def close_position(trade_id):
    session = load_session()
    pos_idx = -1
    for i, p in enumerate(session['positions']):
        if p['id'] == trade_id: pos_idx = i; break
    
    if pos_idx == -1: return "ERR: POS NOT FOUND"
    
    pos = session['positions'][pos_idx]
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    exit_px = black_scholes(price, pos['strike'], T, r, sigma, pos['type'])
    credit = pos['contracts'] * exit_px * 100
    
    session['liquid_cash'] += credit
    session['balance'] = session['liquid_cash'] 
    
    pnl = credit - pos['cost_basis']
    
    log_entry = {
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": pos['ticker'],
        "action": "SELL",
        "qty": pos['contracts'],
        "entry_px": pos['entry_px'],
        "price": exit_px,
        "pnl": pnl,
        "reason": "MANUAL"
    }
    session['trades'].append(log_entry)
    session['positions'].pop(pos_idx)
    save_session(session)
    return f"SOLD @ ${exit_px:.2f} (PnL: ${pnl:.2f})"

def get_portfolio_stats():
    # Load session even if price fails
    session = load_session()
    
    # Try price
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    mkt_val = 0.0
    for p in session['positions']:
        curr = black_scholes(price, p['strike'], T, r, sigma, p['type'])
        mkt_val += curr * 100 * p['contracts']
        
    equity = session['liquid_cash'] + mkt_val
    
    return {
        "balance": equity,
        "liquid": session['liquid_cash'],
        "open_pnl": mkt_val - sum([p['cost_basis'] for p in session['positions']]),
        "open_equity": equity
    }