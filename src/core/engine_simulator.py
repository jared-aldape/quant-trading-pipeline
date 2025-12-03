import pandas as pd
import yfinance as yf
import json
import os
import time
import numpy as np
import math
from datetime import datetime, timedelta
from pathlib import Path
from src.utils import config

# ==============================================================================
# LIVE SESSION STATE MANAGEMENT
# ==============================================================================
SESSION_FILE = config.DATA_DIR / "live_session.json"
ASSUMED_VOLATILITY = 0.15  
RISK_FREE_RATE = 0.045     

# IN-MEMORY CACHE (Prevents API Spam)
_DATA_CACHE = {}
CACHE_DURATION = 15 

def get_live_price(ticker="SPY", use_cache=True):
    """
    Fetches latest price.
    Args:
        use_cache (bool): If True, returns cached data if < 15s old.
                          If False (Trading), forces fresh fetch.
    """
    global _DATA_CACHE
    now = time.time()
    cache_key = f"price_{ticker}"
    
    # 1. Check Cache
    if use_cache and cache_key in _DATA_CACHE:
        timestamp, price = _DATA_CACHE[cache_key]
        if now - timestamp < CACHE_DURATION:
            return price

    # 2. Fetch Fresh
    try:
        sym = "SPY" if "XSP" in ticker else ticker
        # Fetch just 1 day of 1m data to get latest close
        data = yf.Ticker(sym).history(period="1d", interval="1m")
        if data.empty: return None
        
        price = data['Close'].iloc[-1]
        
        # Update Cache
        _DATA_CACHE[cache_key] = (now, price)
        return price
    except:
        return None

def get_live_chart_data(ticker="SPY", interval="5m", period="1d"):
    """
    Fetches chart data AND converts to Local Time (PST).
    """
    global _DATA_CACHE
    now = time.time()
    cache_key = f"chart_{ticker}_{interval}"
    
    if cache_key in _DATA_CACHE:
        timestamp, df = _DATA_CACHE[cache_key]
        if now - timestamp < CACHE_DURATION: return df

    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
        if data.empty: return None
        
        data = data.reset_index()
        
        # --- TIMEZONE CONVERSION ---
        # 1. Ensure Aware (yfinance usually returns NY time)
        if data['Datetime'].dt.tz is None:
            data['Datetime'] = data['Datetime'].dt.tz_localize('America/New_York')
        else:
            data['Datetime'] = data['Datetime'].dt.tz_convert('America/New_York')
            
        # 2. Convert to Project Local (PST)
        data['Datetime'] = data['Datetime'].dt.tz_convert(config.TZ_LOCAL)
        # ---------------------------
        
        _DATA_CACHE[cache_key] = (now, data)
        return data
    except Exception as e:
        print(f"Chart Data Error: {e}")
        return None

def black_scholes(S, K, T, r, sigma, option_type="call"):
    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        from scipy.stats import norm
        if option_type == "call":
            price = (S * norm.cdf(d1, 0.0, 1.0) - K * np.exp(-r * T) * norm.cdf(d2, 0.0, 1.0))
        else:
            price = (K * np.exp(-r * T) * norm.cdf(-d2, 0.0, 1.0) - S * norm.cdf(-d1, 0.0, 1.0))
        return price
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
    
    # FORCE FRESH DATA FOR EXECUTION
    price = get_live_price("SPY", use_cache=False)
    
    if not price: return "Market Data Error"
    if state['active_trade']: return "Trade Already Active (Scale Out First)"
    
    strike = round(price) 
    T = get_time_to_close()
    raw_premium = black_scholes(price, strike, T, RISK_FREE_RATE, ASSUMED_VOLATILITY, trade_type.lower())
    
    slippage = 0.01
    entry_fill = raw_premium + slippage
    contract_cost = entry_fill * 100
    
    num_contracts = 0
    if size_mode == "QTY":
        num_contracts = int(size_val)
    else:
        est_fee = 0.40
        num_contracts = int(size_val / (contract_cost + est_fee))
    
    if num_contracts < 1: 
        return f"Insufficient Funds / Invalid Qty"
        
    total_fees = calculate_fees(num_contracts, fee_model)
    cost_basis = (num_contracts * contract_cost) + total_fees
    
    if cost_basis > state['balance']:
        return f"Insufficient Funds (Need ${cost_basis:.2f})"

    # Use Configured Local Time for Ledger
    entry_time = datetime.now(config.TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")

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
        "stop_loss_px": entry_fill * 0.75,
        "target_px": entry_fill * 2.00,
        "breakeven_active": False
    }
    
    save_session(state)
    return f"Bought {num_contracts} {trade_type}s @ ${entry_fill:.2f}"

def execute_exit(exit_qty=None, reason="MANUAL", fee_model="RH_GOLD"):
    state = load_session()
    trade = state.get('active_trade')
    if not trade: return "No Active Trade"
    
    # FORCE FRESH DATA FOR EXECUTION
    price = get_live_price("SPY", use_cache=False)
    if not price: return "Market Data Error"
    
    T = get_time_to_close()
    raw_premium = black_scholes(price, trade['strike'], T, RISK_FREE_RATE, ASSUMED_VOLATILITY, trade['type'].lower())
    
    slippage = 0.01
    exit_fill = raw_premium - slippage
    
    current_qty = trade['contracts']
    
    if exit_qty is None or exit_qty >= current_qty:
        sell_qty = current_qty
        is_full_close = True
    else:
        sell_qty = int(exit_qty)
        is_full_close = False
        
    if sell_qty < 1: return "Invalid Exit Qty"

    exit_fees = calculate_fees(sell_qty, fee_model)
    gross_proceeds = (sell_qty * exit_fill * 100)
    net_proceeds = gross_proceeds - exit_fees
    chunk_cost_basis = trade['contract_cost_basis'] * sell_qty
    pnl = net_proceeds - chunk_cost_basis
    
    state['balance'] += net_proceeds
    
    # Use Configured Local Time for Ledger
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
        "reason": f"{reason} (Partial)" if not is_full_close else reason
    }
    state['trades'].append(log_entry)
    
    if is_full_close:
        state['active_trade'] = None
    else:
        trade['contracts'] -= sell_qty
        trade['cost_basis'] -= chunk_cost_basis
        state['active_trade'] = trade
    
    save_session(state)
    return f"Sold {sell_qty}. P&L: ${pnl:.2f}"

def reset_session():
    if SESSION_FILE.exists():
        os.remove(SESSION_FILE)
    return load_session()