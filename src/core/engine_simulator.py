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

_MARKET_CACHE = {"price": None, "vix": None, "irx": None, "last_update": 0}
MARKET_CACHE_DURATION = 15

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
            for k, v in DEFAULT_SESSION.items():
                if k not in session: session[k] = v
            return session
    except:
        return DEFAULT_SESSION

def save_session(session):
    with open(SESSION_FILE, 'w') as f:
        json.dump(session, f, indent=4)

def reset_session():
    save_session(DEFAULT_SESSION)
    log.info("Session Reset")

# ==============================================================================
# 3. MARKET DATA & PRICING
# ==============================================================================
def get_live_price(ticker="SPY"):
    """
    Fetches the live price for the underlying.
    TARGET: XSP (Mini-SPX).
    PROXY: SPY (Since SPY ~= XSP ~= SPX/10).
    """
    # Check Cache
    if time_lib.time() - _MARKET_CACHE['last_update'] < MARKET_CACHE_DURATION:
        if _MARKET_CACHE['price']: return _MARKET_CACHE['price']

    try:
        # FIX: REMOVED DIVISOR. SPY (~590) is direct proxy for XSP (~590).
        price = yf.Ticker("SPY").fast_info.last_price
        
        # Fallback sanity check (SPX context)
        if price < 100: # If we somehow got a weird split or bad data
             log.warning(f"Price Anomaly Detected ({price}). Fetching SPX directly...")
             spx = yf.Ticker("^GSPC").fast_info.last_price
             price = spx / 10.0

        _MARKET_CACHE['price'] = price
        _MARKET_CACHE['last_update'] = time_lib.time()
        return price
    except Exception as e:
        log.error(f"Price Fetch Fail: {e}")
        return _MARKET_CACHE['price'] or 590.0 # Default fallback to reasonable XSP level

def get_market_context():
    try:
        if not _MARKET_CACHE['vix']:
            _MARKET_CACHE['vix'] = yf.Ticker("^VIX").fast_info.last_price
            _MARKET_CACHE['irx'] = yf.Ticker("^IRX").fast_info.last_price
        return (_MARKET_CACHE['irx'] or 4.5) / 100.0, (_MARKET_CACHE['vix'] or 15.0) / 100.0
    except:
        return 0.045, 0.15

def get_time_to_close():
    # Fraction of year remaining until 4:00 PM ET today
    ny_tz = pytz.timezone('America/New_York')
    now = datetime.now(ny_tz)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if now >= close: return 0.00001 # Expired
    
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
        
    return max(0.01, price) # Minimum tick $0.01

# ==============================================================================
# 4. VAULT INTEGRATION
# ==============================================================================
def commit_to_vault(trade_record):
    if not config.DB_FILE.exists(): return
    try:
        con = duckdb.connect(str(config.DB_FILE))
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {TBL_SIM_LOG} (
                entry_time TIMESTAMP, exit_time TIMESTAMP, ticker VARCHAR, net_pnl DOUBLE, 
                return_pct DOUBLE, reason VARCHAR, entry_price DOUBLE, exit_price DOUBLE, 
                action VARCHAR, quantity DOUBLE, source_id VARCHAR, status VARCHAR
            )
        """)
        con.execute(f"""
            INSERT INTO {TBL_SIM_LOG} VALUES (
                '{trade_record['entry_ts']}', '{trade_record['exit_ts']}', '{trade_record['ticker']}', 
                {trade_record['pnl']}, {trade_record['return_pct']}, '{trade_record['reason']}', 
                {trade_record['entry_px']}, {trade_record['exit_px']}, 'MANUAL', 
                {trade_record['qty']}, '{trade_record['id']}', 'CLOSED'
            )
        """)
        con.close()
        log.info(f"💾 Manual Trade Committed: {trade_record['ticker']}")
    except Exception as e:
        log.error(f"Vault Commit Failed: {e}")

# ==============================================================================
# 5. LEGACY API ADAPTERS (For View Options Sim)
# ==============================================================================
def preview_entry(qty, limit_px=None, offset=0):
    price = get_live_price()
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    # Calculate Strike
    offset = int(offset) if offset else 0
    atm_strike = round(price) + offset
    
    # Default to Call price for estimation
    opt_price = black_scholes(price, atm_strike, T, r, sigma, 'Call')
    
    if limit_px and limit_px < opt_price: 
        opt_price = limit_px 
    
    total = opt_price * 100 * qty
    return {'total_cost': total, 'est_fill': opt_price, 'strike_desc': f"{atm_strike}"}

def execute_entry(action, qty, order_type='MARKET', offset=0):
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
    
    new_pos = {
        "id": f"SIM_{int(time_lib.time()*1000)}",
        "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": opt_type,
        "strike": atm_strike,
        "contracts": qty,
        "entry_px": opt_price,
        "ticker": f"XSP {opt_type} {atm_strike}",
        "cost_basis": cost
    }
    
    session['positions'].append(new_pos)
    save_session(session)
    return f"BOUGHT {qty}x {opt_type} @ ${opt_price:.2f}"

def execute_exit(trade_id):
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
    ret_pct = (pnl / pos['cost_basis']) * 100 if pos['cost_basis'] > 0 else 0
    exit_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = {
        "exit_time": exit_ts,
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
    
    commit_to_vault({
        'entry_ts': pos['entry_time'], 'exit_ts': exit_ts, 'ticker': pos['ticker'],
        'pnl': pnl, 'return_pct': ret_pct, 'reason': 'MANUAL', 'entry_px': pos['entry_px'],
        'exit_px': exit_px, 'qty': pos['contracts'], 'id': pos['id']
    })
    
    return f"SOLD @ ${exit_px:.2f} (PnL: ${pnl:.2f})"

def get_portfolio_stats():
    session = load_session()
    # Update MTM
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

# ==============================================================================
# 6. CHART DATA
# ==============================================================================
def load_market_data(ticker='SPY', days=5):
    if not config.DB_FILE.exists(): return pd.DataFrame()
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        start_dt = datetime.now() - timedelta(days=days)
        q = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker = '{ticker}' AND datetime_utc >= '{start_dt}' ORDER BY datetime_utc ASC"
        df = con.execute(q).df()
        con.close()
        if not df.empty: df.set_index('datetime_utc', inplace=True)
        return df
    except Exception as e:
        log.error(f"Data Load Error: {e}")
        return pd.DataFrame()