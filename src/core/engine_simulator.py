import pandas as pd
import yfinance as yf
import json
import os
import time
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from src.utils import config

# ==============================================================================
# LIVE SESSION STATE MANAGEMENT
# ==============================================================================
SESSION_FILE = config.DATA_DIR / "live_session.json"

# THROTTLE PROTOCOL
_DATA_CACHE = {}
CACHE_DURATION = 60 

def get_live_price(ticker="SPY", use_cache=True):
    """Fetches latest price. Returns STALE cache if API fails."""
    global _DATA_CACHE
    now = time.time()
    cache_key = f"price_{ticker}"
    
    if use_cache and cache_key in _DATA_CACHE:
        timestamp, price = _DATA_CACHE[cache_key]
        if now - timestamp < CACHE_DURATION: return price

    try:
        sym = "SPY" if "XSP" in ticker else ticker
        data = yf.Ticker(sym).history(period="1d", interval="1m")
        if data.empty: raise ValueError("Empty Data")
        price = data['Close'].iloc[-1]
        _DATA_CACHE[cache_key] = (now, price)
        return price
    except Exception as e:
        if cache_key in _DATA_CACHE: return _DATA_CACHE[cache_key][1]
        return None

def get_market_context(use_cache=True):
    """Fetches Real-Time VIX/IRX. Returns (risk_free_rate, volatility)."""
    global _DATA_CACHE
    now = time.time()
    cache_key = "market_context"
    
    if use_cache and cache_key in _DATA_CACHE:
        timestamp, context = _DATA_CACHE[cache_key]
        if now - timestamp < CACHE_DURATION: return context

    try:
        vix = yf.Ticker("^VIX").history(period="1d", interval="1m")
        irx = yf.Ticker("^IRX").history(period="1d", interval="1m")
        
        sigma = 0.15
        r = 0.045
        
        if not vix.empty: sigma = vix['Close'].iloc[-1] / 100.0
        if not irx.empty: r = irx['Close'].iloc[-1] / 100.0
            
        context = (r, sigma)
        _DATA_CACHE[cache_key] = (now, context)
        return context
    except Exception:
        if cache_key in _DATA_CACHE: return _DATA_CACHE[cache_key][1]
        return (0.045, 0.15) 

def get_vix_metrics():
    """
    PRIORITY BRAVO: Calculates Live VIX RSI for the AI Model.
    Returns: (current_vix_close, current_vix_rsi)
    """
    try:
        # Fetch enough data for RSI-14
        vix = yf.Ticker("^VIX").history(period="5d", interval="5m") 
        if vix.empty: return 15.0, 50.0
        
        # Calculate RSI
        delta = vix['Close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down
        vix['rsi'] = 100 - (100 / (1 + rs))
        
        return vix['Close'].iloc[-1], vix['rsi'].iloc[-1]
    except:
        return 15.0, 50.0

def get_live_chart_data(ticker="SPY", interval="5m", period="1d"):
    """Fetches chart data. Returns STALE cache if API fails."""
    global _DATA_CACHE
    now = time.time()
    cache_key = f"chart_{ticker}_{interval}"
    
    if cache_key in _DATA_CACHE:
        timestamp, df = _DATA_CACHE[cache_key]
        if now - timestamp < CACHE_DURATION: return df

    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
        if data.empty: raise ValueError("Empty Chart")
        data = data.reset_index()
        
        if data['Datetime'].dt.tz is None:
            data['Datetime'] = data['Datetime'].dt.tz_localize('America/New_York')
        else:
            data['Datetime'] = data['Datetime'].dt.tz_convert('America/New_York')
            
        data['Datetime'] = data['Datetime'].dt.tz_convert(config.TZ_LOCAL)
        _DATA_CACHE[cache_key] = (now, data)
        return data
    except Exception:
        if cache_key in _DATA_CACHE: return _DATA_CACHE[cache_key][1]
        return None

def black_scholes(S, K, T, r, sigma, option_type="call"):
    try:
        if T <= 0: return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        from scipy.stats import norm
        if option_type == "call":
            return (S * norm.cdf(d1, 0.0, 1.0) - K * np.exp(-r * T) * norm.cdf(d2, 0.0, 1.0))
        else:
            return (K * np.exp(-r * T) * norm.cdf(-d2, 0.0, 1.0) - S * norm.cdf(-d1, 0.0, 1.0))
    except:
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)

def get_time_to_close():
    now = datetime.now(config.TZ_NY)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now > market_close: return 0.0001
    seconds_left = (market_close - now).total_seconds()
    return seconds_left / (252 * 6.5 * 3600) 

def calculate_fees(num_contracts, fee_model="RH_GOLD"):
    fees = config.RH_FEES
    base = fees['REGULATORY_BASE']
    broker = fees['CONTRACT_GOLD'] if fee_model == "RH_GOLD" else fees['CONTRACT_STD']
    extra = fees['INDEX_EXCHANGE'] if num_contracts >= 10 else 0
    return (base + broker + extra) * num_contracts

def load_session():
    if not SESSION_FILE.exists():
        return {"balance": 600.0, "active_trade": None, "trades": []}
    try:
        with open(SESSION_FILE, 'r') as f: return json.load(f)
    except:
        return {"balance": 600.0, "active_trade": None, "trades": []}

def save_session(state):
    with open(SESSION_FILE, 'w') as f: json.dump(state, f, indent=4)

def execute_entry(trade_type, size_val, size_mode="AMT", fee_model="RH_GOLD"):
    state = load_session()
    price = get_live_price("SPY", use_cache=False)
    if not price: return "Market Data Error"
    if state['active_trade']: return "Trade Already Active"
    
    r, sigma = get_market_context(use_cache=False)
    strike = round(price) 
    T = get_time_to_close()
    
    raw_premium = black_scholes(price, strike, T, r, sigma, trade_type.lower())
    entry_fill = raw_premium + 0.01
    contract_cost = entry_fill * 100
    
    num_contracts = int(size_val / (contract_cost + 0.40)) if size_mode != "QTY" else int(size_val)
    if num_contracts < 1: return f"Insufficient Funds (Prem: ${entry_fill:.2f})"
        
    total_fees = calculate_fees(num_contracts, fee_model)
    cost_basis = (num_contracts * contract_cost) + total_fees
    
    if cost_basis > state['balance']: return f"Insufficient Funds (Need ${cost_basis:.2f})"

    entry_time = datetime.now(config.TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")
    
    # Store VIX RSI for future learning
    vix_close, vix_rsi = get_vix_metrics()
    
    state['balance'] -= cost_basis
    state['active_trade'] = {
        "ticker": f"XSP {int(strike)} {trade_type}",
        "underlying_at_entry": price,
        "strike": strike,
        "type": trade_type,
        "entry_time": entry_time,
        "entry_px": entry_fill,
        "contracts": num_contracts,
        "cost_basis": cost_basis,
        "contract_cost_basis": cost_basis / num_contracts,
        "implied_vol": sigma,
        "vix_rsi_at_entry": vix_rsi, # NEW: Forensic Data
        "risk_free": r
    }
    save_session(state)
    return f"Bought {num_contracts} {trade_type}s @ ${entry_fill:.2f} (IV: {sigma:.2f})"

def execute_exit(exit_qty=None, reason="MANUAL", fee_model="RH_GOLD"):
    state = load_session()
    trade = state.get('active_trade')
    if not trade: return "No Active Trade"
    
    price = get_live_price("SPY", use_cache=False)
    r, sigma = get_market_context(use_cache=False)
    T = get_time_to_close()
    
    raw_premium = black_scholes(price, trade['strike'], T, r, sigma, trade['type'].lower())
    exit_fill = raw_premium - 0.01
    
    current_qty = trade['contracts']
    sell_qty = current_qty if (exit_qty is None or exit_qty >= current_qty) else int(exit_qty)
    is_full_close = (sell_qty == current_qty)

    exit_fees = calculate_fees(sell_qty, fee_model)
    gross_proceeds = (sell_qty * exit_fill * 100)
    net_proceeds = gross_proceeds - exit_fees
    chunk_cost_basis = trade['contract_cost_basis'] * sell_qty
    pnl = net_proceeds - chunk_cost_basis
    
    state['balance'] += net_proceeds
    exit_time = datetime.now(config.TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = {
        "ticker": trade['ticker'],
        "type": trade['type'],
        "entry_time": trade['entry_time'],
        "entry_px": trade['entry_px'],
        "exit_time": exit_time,
        "exit_px": exit_fill,
        "contracts": sell_qty,
        "pnl": pnl,
        "reason": reason,
        "exit_iv": sigma
    }
    state['trades'].append(log_entry)
    
    if is_full_close: state['active_trade'] = None
    else:
        trade['contracts'] -= sell_qty
        trade['cost_basis'] -= chunk_cost_basis
        state['active_trade'] = trade
    
    save_session(state)
    return f"Sold {sell_qty}. P&L: ${pnl:.2f}"

def reset_session():
    if SESSION_FILE.exists(): os.remove(SESSION_FILE)
    return load_session()