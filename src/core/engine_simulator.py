import pandas as pd
import yfinance as yf
import json
import os
import time
import uuid
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from src.utils import config

# ==============================================================================
# LIVE SESSION STATE MANAGEMENT (MULTI-LOT ARCHITECTURE)
# ==============================================================================
SESSION_FILE = config.DATA_DIR / "live_session.json"
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
        # Return stale data if available, else None
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
    """
    Standard Black-Scholes Model.
    CRITICAL FIX: Added Guard Clause for NoneType price (Offline/API Fail).
    """
    # --- GUARD CLAUSE ---
    if S is None or S <= 0:
        return 0.0

    try:
        if T <= 0: return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        from scipy.stats import norm
        
        if option_type == "call":
            return (S * norm.cdf(d1, 0.0, 1.0) - K * np.exp(-r * T) * norm.cdf(d2, 0.0, 1.0))
        else:
            return (K * np.exp(-r * T) * norm.cdf(-d2, 0.0, 1.0) - S * norm.cdf(-d1, 0.0, 1.0))
    except Exception:
        # Fallback for any math errors (e.g. T=0 or overflow)
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)

def get_time_to_close():
    now = datetime.now(config.TZ_NY)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now > market_close: return 0.0001
    seconds_left = (market_close - now).total_seconds()
    return seconds_left / (252 * 6.5 * 3600) 

def calculate_detailed_fees(num_contracts, fee_model="RH_GOLD"):
    """
    Returns breakdown: (total_fee, reg_fee, contract_fee)
    Matches Robinhood logic: 
    - Reg Fee (SEC/TAF): ~$0.04 base
    - Contract Fee: $0.35 (Gold) or $0.50 (Std)
    """
    fees = config.RH_FEES
    reg_base = fees.get('REGULATORY_BASE', 0.04) 
    
    # Per contract fee
    broker_rate = fees['CONTRACT_GOLD'] if fee_model == "RH_GOLD" else fees['CONTRACT_STD']
    
    # Calculate
    contract_fees = broker_rate * num_contracts
    reg_fees = reg_base # Simplified per-order reg fee
    
    total = contract_fees + reg_fees
    return total, reg_fees, contract_fees

def load_session():
    # Schema Migration: Ensure 'positions' list exists
    default = {"balance": 600.0, "start_balance": 600.0, "positions": [], "trades": []}
    if not SESSION_FILE.exists(): return default
    try:
        with open(SESSION_FILE, 'r') as f: 
            data = json.load(f)
            
            # MIGRATION: Ensure start_balance exists for P&L tracking
            if 'start_balance' not in data:
                data['start_balance'] = 600.0

            # MIGRATION: If old 'active_trade' exists, move it to 'positions'
            if 'active_trade' in data and data['active_trade'] is not None:
                data['active_trade']['trade_id'] = str(uuid.uuid4())
                if 'fees_total' not in data['active_trade']:
                    data['active_trade']['fees_total'] = 0.54 
                    data['active_trade']['fees_reg'] = 0.04
                    data['active_trade']['fees_contract'] = 0.50

                if 'positions' not in data: data['positions'] = []
                data['positions'].append(data['active_trade'])
                del data['active_trade'] 
            
            if 'positions' not in data: data['positions'] = []
            return data
    except: return default

def save_session(state):
    with open(SESSION_FILE, 'w') as f: json.dump(state, f, indent=4)

def get_portfolio_stats():
    """
    NEW: Calculates Total Account Value (Liquid + Open Positions M2M)
    Returns dictionary with P&L metrics.
    """
    state = load_session()
    start_bal = state.get('start_balance', 600.0)
    liquid_cash = state['balance']
    
    # Calculate Market Value of Open Positions
    open_equity = 0.0
    price = get_live_price("SPY", use_cache=True)
    
    if price:
        r, sigma = get_market_context(use_cache=True)
        T = get_time_to_close()
        for p in state['positions']:
            # M2M Valuation
            opt_val = black_scholes(price, p['strike'], T, r, sigma, p['type'].lower())
            open_equity += (opt_val * 100 * p['contracts'])
            
    total_value = liquid_cash + open_equity
    pnl_abs = total_value - start_bal
    pnl_pct = (pnl_abs / start_bal) * 100 if start_bal > 0 else 0.0
    
    return {
        "liquid_cash": liquid_cash,
        "open_equity": open_equity,
        "total_value": total_value,
        "pnl_abs": pnl_abs,
        "pnl_pct": pnl_pct
    }

def preview_entry(qty, limit_price=None, fee_model="RH_GOLD"):
    """
    NEW: Estimates cost without executing trade.
    Returns dictionary with breakdown.
    """
    try:
        qty = int(qty)
        if qty < 1: return None
        
        # Determine Price Source
        if limit_price and float(limit_price) > 0:
            est_fill = float(limit_price)
            is_estimated = False
            price_source = "LIMIT"
        else:
            # Market Order Simulation (ATM Proxy)
            price = get_live_price("SPY", use_cache=True)
            if not price: return None # <--- GUARD: Return None if Offline
            
            r, sigma = get_market_context(use_cache=True)
            strike = round(price)
            T = get_time_to_close()
            
            # Safe call to BS
            raw = black_scholes(price, strike, T, r, sigma, "call")
            est_fill = raw + 0.01 # Slippage simulation
            is_estimated = True
            price_source = f"MKT (~${est_fill:.2f})"

        contract_cost = est_fill * 100
        total_fee, reg_fee, broker_fee = calculate_detailed_fees(qty, fee_model)
        total_cost = (qty * contract_cost) + total_fee
        
        return {
            "est_fill": est_fill,
            "qty": qty,
            "fees_total": total_fee,
            "fees_reg": reg_fee,
            "fees_contract": broker_fee,
            "total_cost": total_cost,
            "is_estimated": is_estimated,
            "source": price_source
        }
    except Exception as e:
        return None

def execute_entry(trade_type, size_val, size_mode="AMT", fee_model="RH_GOLD"):
    """
    Supports Multiple Positions (Scaling In).
    Appends new lot to 'positions' list with unique ID.
    """
    state = load_session()
    price = get_live_price("SPY", use_cache=False)
    
    # GUARD: Ensure we have price data
    if not price: return "Market Data Error (Offline)"
    
    r, sigma = get_market_context(use_cache=False)
    strike = round(price) 
    T = get_time_to_close()
    
    raw_premium = black_scholes(price, strike, T, r, sigma, trade_type.lower())
    entry_fill = raw_premium + 0.01 # Slippage
    contract_cost = entry_fill * 100
    
    # Determine Quantity
    if size_mode == "QTY":
        num_contracts = int(size_val)
    else:
        num_contracts = int(size_val / (contract_cost + 0.40))
        
    if num_contracts < 1: return f"Insufficient Funds (Prem: ${entry_fill:.2f})"
        
    # Detailed Fee Calculation
    total_fee, reg_fee, broker_fee = calculate_detailed_fees(num_contracts, fee_model)
    cost_basis = (num_contracts * contract_cost) + total_fee
    
    if cost_basis > state['balance']: return f"Insufficient Funds (Need ${cost_basis:.2f})"

    state['balance'] -= cost_basis
    
    # Generate Unique ID for this specific lot
    trade_id = str(uuid.uuid4())
    entry_time = datetime.now(config.TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")
    vix_close, vix_rsi = get_vix_metrics()

    new_position = {
        "trade_id": trade_id, 
        "ticker": f"XSP {int(strike)} {trade_type}",
        "underlying_at_entry": price,
        "strike": strike,
        "type": trade_type,
        "entry_time": entry_time,
        "entry_px": entry_fill,
        "contracts": num_contracts,
        "cost_basis": cost_basis,           
        "fees_total": total_fee,            
        "fees_reg": reg_fee,                
        "fees_contract": broker_fee,        
        "implied_vol": sigma,
        "vix_rsi_at_entry": vix_rsi,
        "risk_free": r
    }
    
    state['positions'].append(new_position)
    save_session(state)
    return f"Executed: {num_contracts}x {trade_type} @ ${entry_fill:.2f} (ID: {trade_id[:4]})"

def execute_exit(trade_id, exit_qty=None, reason="MANUAL", fee_model="RH_GOLD"):
    """
    Exits a specific trade ID, supporting partials.
    Requires trade_id to identify which lot to sell.
    """
    state = load_session()
    positions = state.get('positions', [])
    
    # Find the specific trade by UUID
    target_trade = next((p for p in positions if p['trade_id'] == trade_id), None)
    if not target_trade: return "Trade ID Not Found"
    
    price = get_live_price("SPY", use_cache=False)
    
    # GUARD: Use entry price if offline to allow emergency close (optional)
    # But safer to just block or use Last Known
    if not price: return "Cannot Close: Market Offline"
    
    r, sigma = get_market_context(use_cache=False)
    T = get_time_to_close()
    
    # Calculate Exit Price
    raw_premium = black_scholes(price, target_trade['strike'], T, r, sigma, target_trade['type'].lower())
    exit_fill = raw_premium - 0.01 # Slippage
    
    current_qty = target_trade['contracts']
    sell_qty = current_qty if (exit_qty is None or exit_qty >= current_qty) else int(exit_qty)
    
    # Calculate Financials
    total_exit_fees, _, _ = calculate_detailed_fees(sell_qty, fee_model)
    gross_proceeds = (sell_qty * exit_fill * 100)
    net_proceeds = gross_proceeds - total_exit_fees
    
    # Pro-rated Cost Basis for this chunk (Cost basis includes entry fees)
    pct_sold = sell_qty / current_qty
    chunk_cost_basis = target_trade['cost_basis'] * pct_sold
    
    pnl = net_proceeds - chunk_cost_basis
    state['balance'] += net_proceeds
    
    exit_time = datetime.now(config.TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")
    
    # Log to History
    log_entry = {
        "trade_id": target_trade['trade_id'],
        "ticker": target_trade['ticker'],
        "type": target_trade['type'],
        "entry_time": target_trade['entry_time'],
        "entry_px": target_trade['entry_px'],
        "exit_time": exit_time,
        "exit_px": exit_fill,
        "contracts": sell_qty,
        "cost_basis": chunk_cost_basis, # Cost of sold portion
        "proceeds": net_proceeds,
        "pnl": pnl,
        "reason": reason,
        "fees": total_exit_fees
    }
    state['trades'].append(log_entry)
    
    # Update Position State
    if sell_qty == current_qty:
        positions.remove(target_trade)
    else:
        # Update remaining portion
        target_trade['contracts'] -= sell_qty
        target_trade['cost_basis'] -= chunk_cost_basis
        target_trade['fees_total'] = target_trade['fees_total'] * (1 - pct_sold)
        # Entry price/strike/id remain the same for the remaining contracts
    
    state['positions'] = positions
    save_session(state)
    return f"Sold {sell_qty} (ID: {trade_id[:4]}). P&L: ${pnl:.2f}"

def reset_session():
    if SESSION_FILE.exists(): os.remove(SESSION_FILE)
    return load_session()