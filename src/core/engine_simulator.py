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
_MARKET_CACHE = {"price": 580.0, "vix": 0.15, "irx": 0.045, "last_update": 0}
MARKET_CACHE_DURATION = 15 # Seconds to wait between Yahoo calls

# ==============================================================================
# 2. SESSION MANAGEMENT
# ==============================================================================
def load_session():
    if not SESSION_FILE.exists():
        save_session(DEFAULT_SESSION)
        return DEFAULT_SESSION
    try:
        with open(SESSION_FILE, 'r') as f:
            session = json.load(f)
            session = process_expiration(session)
            return session
    except Exception as e:
        log.error(f"Session Corrupt: {e}")
        return DEFAULT_SESSION

def save_session(session):
    with open(SESSION_FILE, 'w') as f:
        json.dump(session, f, indent=4)

def process_expiration(session):
    """Enforces 0DTE Logic: Expire worthless if past 16:00 ET."""
    now_ny = datetime.now(config.TZ_NY)
    market_close = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if now_ny > market_close and len(session['positions']) > 0:
        log.info("MARKET CLOSED. EXPIRING POSITIONS.")
        for pos in session['positions']:
            log_entry = {
                "exit_time": now_ny.strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": pos['ticker'],
                "action": "EXPIRED",
                "qty": pos['contracts'],
                "entry_px": pos['entry_px'],
                "price": 0.00,
                "pnl": -(pos['cost_basis']),
                "reason": "0DTE_CLOSE"
            }
            session['trades'].append(log_entry)
        session['positions'] = []
        session['balance'] = session['liquid_cash'] 
        save_session(session)
    return session

def reset_session():
    save_session(DEFAULT_SESSION)
    return "DECK RESET. GOOD LUCK."

# ==============================================================================
# 3. MARKET DATA ENGINE (GREEKS)
# ==============================================================================
def get_live_price():
    global _MARKET_CACHE
    now = time_lib.time()
    if now - _MARKET_CACHE['last_update'] < MARKET_CACHE_DURATION: return _MARKET_CACHE['price']

    try:
        ticker = yf.Ticker("^XSP")
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            _MARKET_CACHE['price'] = price
            _MARKET_CACHE['last_update'] = now
            return price
        
        spy = yf.Ticker("SPY").history(period="1d", interval="1m")
        if not spy.empty:
            price = spy['Close'].iloc[-1] * 10
            _MARKET_CACHE['price'] = price
            _MARKET_CACHE['last_update'] = now
            return price
    except Exception as e: log.error(f"Price Fetch Fail: {e}")
    return _MARKET_CACHE['price']

def get_market_context(): return 0.045, 0.15 # r, sigma

def black_scholes(S, K, T, r, sigma, option_type="call"):
    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        if option_type == "call": price = (S * norm.cdf(d1, 0.0, 1.0) - K * np.exp(-r * T) * norm.cdf(d2, 0.0, 1.0))
        else: price = (K * np.exp(-r * T) * norm.cdf(-d2, 0.0, 1.0) - S * norm.cdf(-d1, 0.0, 1.0))
        return max(0.01, price)
    except: return 0.01

def get_time_to_close():
    now = datetime.now(config.TZ_NY)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now >= close: return 0.0001
    return (close - now).total_seconds() / (365 * 24 * 3600)

# ==============================================================================
# 4. TRADING LOGIC
# ==============================================================================
def generate_strikes(current_price, trade_type="CALL"):
    center = round(current_price)
    strikes = []
    for k in range(center - 15, center + 16):
        is_itm = (k < current_price) if trade_type == "CALL" else (k > current_price)
        diff = abs(current_price - k)
        
        # Calculate theoretical price for display
        T = get_time_to_close()
        r, sigma = get_market_context()
        theo_price = black_scholes(current_price, k, T, r, sigma, trade_type.lower())
        
        label = f"${k} (ATM) - ${theo_price:.2f}" if diff < 0.5 else \
                f"${k} (ITM) - ${theo_price:.2f}" if is_itm else \
                f"${k} (OTM) - ${theo_price:.2f}"
                
        strikes.append({"label": label, "value": k})
    return strikes

def execute_trade(strike, contracts, trade_type, order_type="MARKET", limit_price=0.0):
    session = load_session()
    now_ny = datetime.now(config.TZ_NY)
    if now_ny.time() >= time(16, 0): return "MARKET CLOSED"
    
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    # 1. Quote Real Cost
    cost_per_share = black_scholes(price, strike, T, r, sigma, trade_type.lower())
    
    # 2. Limit Check
    if order_type == "LIMIT":
        # Buying: Limit must be >= Ask (We assume Ask ~ Last for Sim)
        if limit_price < cost_per_share:
            return f"LIMIT NOT MET (Ask: ${cost_per_share:.2f})"
    
    # Fill at Market Price (simulating instant fill)
    fill_price = cost_per_share
    
    cost_basis = fill_price * 100 * contracts
    fees = (contracts * 0.03) + (contracts * 1.00)
    total_cost = cost_basis + fees
    
    if session['liquid_cash'] < total_cost: return "INSUFFICIENT FUNDS"
    
    session['liquid_cash'] -= total_cost
    new_pos = {
        "id": int(time_lib.time() * 1000),
        "entry_time": datetime.now().strftime("%H:%M:%S"),
        "ticker": f"XSP {strike}{trade_type[0]}",
        "strike": strike,
        "type": trade_type.lower(),
        "contracts": contracts,
        "entry_px": fill_price,
        "cost_basis": total_cost,
        "current_val": cost_basis
    }
    session['positions'].append(new_pos)
    save_session(session)
    return "ORDER FILLED"

def close_position(pos_id):
    session = load_session()
    pos_idx = -1
    pos = None
    for i, p in enumerate(session['positions']):
        if p['id'] == pos_id:
            pos_idx = i
            pos = p
            break
            
    if not pos: return "POSITION NOT FOUND"
    
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
    return f"SOLD @ ${exit_px:.2f}"

def get_portfolio_stats():
    session = load_session()
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    equity_val = 0.0
    for p in session['positions']:
        mark = black_scholes(price, p['strike'], T, r, sigma, p['type'])
        val = mark * 100 * p['contracts']
        p['current_val'] = val
        equity_val += val
        
    total_liquidity = session['liquid_cash'] + equity_val
    
    return {
        "balance": total_liquidity,
        "cash": session['liquid_cash'],
        "equity": equity_val,
        "day_pnl": total_liquidity - 2000.0,
        "positions": session['positions'],
        "price": price
    }

def fetch_recent_transactions():
    session = load_session()
    df = pd.DataFrame(session['trades'])
    if df.empty: return []
    return df.sort_values("exit_time", ascending=False).head(50).to_dict('records')