import pandas as pd
import yfinance as yf
import json
import os
import time
import uuid
import duckdb
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SimEngine")

# ==============================================================================
# 1. CONFIGURATION & STATE
# ==============================================================================
SESSION_FILE = config.DATA_DIR / "live_session.json"
_DATA_CACHE = {}
CACHE_DURATION = 15  # Cached for 15s to prevent API spam

def load_session():
    """Loads the live session. Defaults to $2,000 start."""
    default = {
        "balance": 2000.0, 
        "start_balance": 2000.0, 
        "positions": [], 
        "trades": [] 
    }
    if not SESSION_FILE.exists(): return default
    try:
        with open(SESSION_FILE, 'r') as f: 
            data = json.load(f)
            if 'start_balance' not in data: data['start_balance'] = 2000.0
            return data
    except: return default

def save_session(state):
    with open(SESSION_FILE, 'w') as f: json.dump(state, f, indent=4)

def reset_session():
    if SESSION_FILE.exists(): os.remove(SESSION_FILE)
    return load_session()

# ==============================================================================
# 2. DATA FEED (OPTIMIZED WATCHDOG)
# ==============================================================================
def get_live_price(ticker="SPY", use_cache=True):
    """
    Fetches price with Smart Caching.
    If API fails, caches the Vault Price to prevent log spam/lag.
    """
    global _DATA_CACHE
    now = time.time()
    cache_key = f"price_{ticker}"
    
    # 1. Memory Cache
    if use_cache and cache_key in _DATA_CACHE:
        # Serve cache if within duration
        if now - _DATA_CACHE[cache_key][0] < CACHE_DURATION: 
            return _DATA_CACHE[cache_key][1]

    try:
        target_sym = ticker
        if "XSP" in ticker: target_sym = "^XSP"
        
        try:
            # 2. Primary API (3s Timeout for speed)
            data = yf.Ticker(target_sym).history(period="1d", interval="1m", timeout=3)
            
            # XSP Fallback
            if data.empty and "XSP" in ticker:
                target_sym = "SPY"
                data = yf.Ticker(target_sym).history(period="1d", interval="1m", timeout=3)
            
            if data.empty: raise ValueError("No Data Returned")
            
            price = data['Close'].iloc[-1]
            _DATA_CACHE[cache_key] = (now, price)
            return price

        except Exception:
            # Proxy Retry
            if "XSP" in ticker and target_sym != "SPY":
                data = yf.Ticker("SPY").history(period="1d", interval="1m", timeout=3)
                if not data.empty:
                    price = data['Close'].iloc[-1]
                    _DATA_CACHE[cache_key] = (now, price)
                    return price
            raise

    except Exception as e:
        # 3. Vault Fallback + FAILURE CACHING
        try:
            con = duckdb.connect(str(config.DB_FILE), read_only=True)
            query = f"SELECT close FROM {config.TBL_INDICES} WHERE ticker IN ('SPX', 'SPY') ORDER BY datetime_utc DESC LIMIT 1"
            latest = con.execute(query).fetchone()
            con.close()
            
            if latest:
                price = latest[0]
                if price > 2000 and "XSP" in ticker: price /= 10.0
                
                # CRITICAL FIX: CACHE THE FALLBACK PRICE
                # This stops the system from trying the broken API again for 15 seconds.
                _DATA_CACHE[cache_key] = (now, price)
                
                log.warning(f"🟠 Watchdog: Using Vault Price: {price:.2f} (Cached 15s)")
                return price
        except: pass
            
        # Last Resort: Return old cache even if expired
        if cache_key in _DATA_CACHE:
            return _DATA_CACHE[cache_key][1]

        log.error(f"🔴 DATA BLACKOUT: Could not find price for {ticker}")
        return None

def get_live_chart_data(ticker="SPY", interval="5m", period="1d"):
    """Fetches OHLC data for charting."""
    global _DATA_CACHE
    now = time.time()
    cache_key = f"chart_{ticker}_{interval}"
    
    if cache_key in _DATA_CACHE:
        if now - _DATA_CACHE[cache_key][0] < CACHE_DURATION: return _DATA_CACHE[cache_key][1]

    try:
        sym = ticker
        if ticker == "SPY": sym = "SPY"
        if ticker == "^VIX": sym = "^VIX"

        data = yf.Ticker(sym).history(period=period, interval=interval, timeout=5)
        if data.empty: return None
        
        data = data.reset_index()
        
        if data['Datetime'].dt.tz is None:
            data['Datetime'] = data['Datetime'].dt.tz_localize('America/New_York')
        else:
            data['Datetime'] = data['Datetime'].dt.tz_convert('America/New_York')
            
        data['Datetime'] = data['Datetime'].dt.tz_convert(config.TZ_LOCAL)
        
        _DATA_CACHE[cache_key] = (now, data)
        return data
    except Exception as e:
        return None

def get_market_context(use_cache=True):
    return 0.045, 0.15

# ==============================================================================
# 3. CORE LOGIC (Greeks & Fees)
# ==============================================================================
def calculate_detailed_fees(num_contracts, fee_model="RH_GOLD"):
    fees = config.RH_FEES
    reg_base = fees.get('REGULATORY_BASE', 0.04) 
    broker_rate = fees['CONTRACT_GOLD'] if fee_model == "RH_GOLD" else fees['CONTRACT_STD']
    contract_fees = broker_rate * num_contracts
    reg_fees = reg_base 
    total = contract_fees + reg_fees
    return total, reg_fees, contract_fees

def black_scholes(S, K, T, r, sigma, option_type="call"):
    if S is None or S <= 0: return 0.0
    if T <= 0: return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    try:
        from scipy.stats import norm
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        if option_type == "call":
            return (S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
        else:
            return (K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))
    except:
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)

def get_time_to_close():
    now = datetime.now(config.TZ_NY)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now >= market_close: return 0.0
    return (market_close - now).total_seconds() / (252 * 6.5 * 3600)

def get_vix_metrics():
    try:
        v = yf.Ticker("^VIX").history(period="5d", interval="5m", timeout=3)
        if v.empty: return 15.0, 50.0
        
        delta = v['Close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down
        rsi = 100 - (100 / (1 + rs))
        
        return v['Close'].iloc[-1], rsi.iloc[-1]
    except: 
        return 15.0, 50.0

# ==============================================================================
# 4. TRANSACTIONAL LOGGING
# ==============================================================================
def log_transaction_to_vault(action, ticker, qty, price, fees, cash_impact, balance):
    try:
        con = duckdb.connect(str(config.DB_FILE))
        trans_id = str(uuid.uuid4())
        ts = datetime.now(config.TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S")
        
        query = f"""
        INSERT INTO {config.TBL_LIVE_LOG} VALUES (
            '{trans_id}', '{ts}', '{ticker}', '{action}', {qty}, {price},
            {fees}, {cash_impact}, {balance}, 'MANUAL', ''
        )
        """
        con.execute(query)
        con.close()
        log.info(f"💾 Logged {action} {ticker}: ${cash_impact:+.2f}")
    except Exception as e:
        log.error(f"Ledger Write Failed: {e}")

# ==============================================================================
# 5. EXECUTION HANDLERS
# ==============================================================================
def execute_entry(trade_type, size_val, size_mode="AMT", fee_model="RH_GOLD"):
    state = load_session()
    price = get_live_price("XSP")
    if not price: return "Market Data Error"
    
    strike = round(price)
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    raw_prem = black_scholes(price, strike, T, r, sigma, trade_type.lower())
    fill_price = max(0.01, raw_prem + 0.02) 
    
    contract_cost = fill_price * 100
    num_contracts = int(size_val) if size_mode == "QTY" else 1
    
    total_fees, _, _ = calculate_detailed_fees(num_contracts, fee_model)
    total_debit = (num_contracts * contract_cost) + total_fees
    
    if total_debit > state['balance']: return "Insufficient Funds"

    state['balance'] -= total_debit
    trade_id = str(uuid.uuid4())
    ticker_str = f"XSP {int(strike)} {trade_type}"
    
    new_pos = {
        "trade_id": trade_id, "ticker": ticker_str, "contracts": num_contracts,
        "entry_px": fill_price, "strike": strike, "type": trade_type,
        "entry_time": datetime.now().strftime("%H:%M:%S")
    }
    state['positions'].append(new_pos)
    save_session(state)
    
    log_transaction_to_vault("BUY", ticker_str, num_contracts, fill_price, total_fees, -total_debit, state['balance'])
    return f"Bought {num_contracts}x {ticker_str}"

def execute_exit(trade_id, exit_qty=None):
    state = load_session()
    target = next((p for p in state['positions'] if p['trade_id'] == trade_id), None)
    if not target: return "Position Not Found"
    
    price = get_live_price("XSP")
    if not price: return "Market Data Error"
    
    r, sigma = get_market_context()
    T = get_time_to_close()
    
    raw_prem = black_scholes(price, target['strike'], T, r, sigma, target['type'].lower())
    fill_price = max(0.01, raw_prem - 0.02)
    
    qty = target['contracts']
    total_fees, _, _ = calculate_detailed_fees(qty, "RH_GOLD")
    gross_credit = (qty * fill_price * 100)
    net_credit = gross_credit - total_fees
    
    state['balance'] += net_credit
    state['positions'].remove(target)
    save_session(state)
    
    log_transaction_to_vault("SELL", target['ticker'], qty, fill_price, total_fees, net_credit, state['balance'])
    return f"Sold {target['ticker']}"

# ==============================================================================
# 6. UI HELPERS
# ==============================================================================
def get_portfolio_stats():
    state = load_session()
    liquid = state['balance']
    price = get_live_price("XSP") or 0
    equity = 0.0
    for p in state['positions']:
        val = max(0, price - p['strike']) if p['type'] == 'CALL' else max(0, p['strike'] - price)
        equity += (val + 0.50) * 100 * p['contracts']
    start = state['start_balance']
    total = liquid + equity
    pnl = total - start
    pct = (pnl / start) * 100 if start > 0 else 0
    return {"liquid_cash": liquid, "open_equity": equity, "total_value": total, "pnl_abs": pnl, "pnl_pct": pct}

def preview_entry(qty, limit):
    price = get_live_price("XSP") or 0
    est_fill = (price * 0.005) + 1.0 
    fees = (0.35 * qty) + 0.04
    total = (est_fill * 100 * qty) + fees
    return {"est_fill": est_fill, "total_cost": total, "fees_total": fees, "fees_reg": 0.04, "fees_contract": 0.35*qty, "qty": qty}