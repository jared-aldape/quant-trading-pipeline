import sys
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

# ==============================================================================
# PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
import src.core.strat_fractal as strat_fractal
from src.core import engine_simulator

log = get_logger("Sentinel")
SCAN_INTERVAL = 60 

# ==============================================================================
# 0. TACTICAL CONFIGURATION (THE TOGGLE)
# ==============================================================================
# MODES: "ALL" (Calls & Puts), "CALLS" (Bull Only), "PUTS" (Bear Only)
SENTINEL_MODE = "ALL" 

# ==============================================================================
# 1. ORB INTELLIGENCE
# ==============================================================================
def get_orb_levels(ticker="SPY"):
    now_ny = datetime.now(config.TZ_NY)
    today_str = now_ny.strftime('%Y-%m-%d')
    orb_start = config.TZ_NY.localize(datetime.combine(now_ny.date(), dtime(9, 30)))
    orb_end = orb_start + timedelta(minutes=config.ORB_WINDOW_MINUTES)
    
    if now_ny < orb_end: return None, None
    try:
        df = yf.Ticker(ticker).history(start=today_str, interval="1m")
        if df.empty: return None, None
        if df.index.tz is None: df.index = df.index.tz_localize(config.TZ_NY)
        else: df.index = df.index.tz_convert(config.TZ_NY)
        orb_df = df[(df.index >= orb_start) & (df.index < orb_end)]
        if orb_df.empty: return None, None
        return orb_df['High'].max(), orb_df['Low'].min()
    except: return None, None

# ==============================================================================
# 2. MARKET DATA
# ==============================================================================
def fetch_live_vix():
    try:
        vix_1h = yf.Ticker("^VIX").history(period="5d", interval="1h")
        vix_5m = yf.Ticker("^VIX").history(period="5d", interval="5m")
        if vix_1h.empty or vix_5m.empty: return None, None
        vix_1h.index = vix_1h.index.tz_convert(config.TZ_NY)
        vix_5m.index = vix_5m.index.tz_convert(config.TZ_NY)
        return vix_1h, vix_5m
    except: return None, None

def get_live_price(ticker="SPY"):
    try:
        data = yf.Ticker(ticker).history(period="1d", interval="1m")
        if not data.empty: return data['Close'].iloc[-1]
    except: pass
    return 0.0

# ==============================================================================
# 3. ALERTING (DUAL STRIKE PICKER)
# ==============================================================================
def dispatch_alert(signal_data, gatekeeper_note="", orb_status=""):
    timestamp = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S")
    spy_price = get_live_price("SPY")
    bias = signal_data.get('signal_type', 'NEUTRAL') 
    
    # --- ADAPTIVE STRIKE PICKER ---
    if "BULL" in bias:
        # Calls: Round UP + 1 Strike OTM
        suggested_strike = int(spy_price) + 1
        contract_type = "CALL"
        color = 5763719 # GREEN
    else:
        # Puts: Round DOWN - 1 Strike OTM
        suggested_strike = int(spy_price) - 1
        contract_type = "PUT"
        color = 15548997 # RED (BEAR/MAYDAY)

    # Visual Output for Command Deck
    print("\n" + "="*60)
    print(f"🚨 MAGITEK SENTINEL ALERT // {timestamp}")
    print(f"TYPE:    {bias} ({contract_type})")
    print(f"STATUS:  {gatekeeper_note}")
    print(f"SPY:     ${spy_price:.2f}")
    print(f"TARGET:  XSP ${suggested_strike} {contract_type}")
    print("="*60 + "\n")

    if config.ENABLE_DISCORD and "http" in config.DISCORD_WEBHOOK:
        payload = {
            "username": "Magitek Sentinel",
            "avatar_url": "https://i.imgur.com/6A4C9fD.png",
            "embeds": [{
                "title": f"⚔️ {contract_type} SIGNAL CONFIRMED",
                "color": color, 
                "fields": [
                    {"name": "Trigger Price (SPY)", "value": f"${spy_price:.2f}", "inline": True},
                    {"name": "Suggested XSP Contract", "value": f"**Strike: {suggested_strike} {contract_type}** (0DTE)\nBias: {bias}", "inline": True},
                    {"name": "Execution Note", "value": gatekeeper_note, "inline": False},
                    {"name": "Fractal Logic", "value": signal_data.get('reason', 'N/A'), "inline": False}
                ],
                "footer": {"text": f"Quant OS {config.SYSTEM_VERSION} | Mode: {SENTINEL_MODE}"}
            }]
        }
        try: requests.post(config.DISCORD_WEBHOOK, json=payload)
        except Exception as e: log.error(f"Discord Dispatch Error: {e}")

# ==============================================================================
# 4. MAIN LOOP (OMNI-DIRECTIONAL)
# ==============================================================================
def run_sentinel():
    print(f"\n   MAGITEK SENTINEL {config.SYSTEM_VERSION} // TACTICAL COMMAND ACTIVE")
    print(f"   [✓] ORB MONITOR:     ARMED ({config.ORB_WINDOW_MINUTES}m)")
    print(f"   [⚔️] MODE:            {SENTINEL_MODE}")
    
    orb_high, orb_low = None, None
    orb_end_time = (datetime.combine(datetime.today(), dtime(9, 30)) + timedelta(minutes=config.ORB_WINDOW_MINUTES)).time()
    
    while True:
        try:
            now_ny = datetime.now(config.TZ_NY)
            current_time = now_ny.time()
            
            # 1. Market Hours Guard
            if now_ny.weekday() >= 5 or current_time < dtime(9, 30) or current_time >= dtime(16, 0):
                print(f"\r[SLEEP] Market Closed ({now_ny.strftime('%H:%M')})...", end="")
                time.sleep(300); continue

            # 2. ORB Observation Phase
            if current_time < orb_end_time:
                print(f"\r[OBSERVE] Forming ORB (Ends {orb_end_time.strftime('%H:%M')} ET)... SPY: ${get_live_price():.2f}", end="")
                time.sleep(30); continue
            
            if orb_high is None:
                orb_high, orb_low = get_orb_levels("SPY")
                if orb_high: print(f"\n[🔒] ORB LOCKED: H:{orb_high:.2f} | L:{orb_low:.2f}")
                else: time.sleep(10); continue

            # 3. Scanning Phase
            print(f"\r[SCAN] VIX Structures... SPY: ${get_live_price():.2f}", end="")
            
            vix_1h, vix_5m = fetch_live_vix()
            if vix_1h is None: continue
            
            # Calculate Indicators
            vix_1h_macd = strat_fractal.calculate_macd(vix_1h)
            vix_5m_macd = strat_fractal.calculate_macd(vix_5m)
            current_rsi = strat_fractal.calculate_rsi(vix_5m).iloc[-1]['rsi']
            
            # Check Fractal Alignment
            res = strat_fractal.check_fractal_flow(
                vix_1h_macd, vix_5m_macd, 
                pd.Timestamp.now(tz=config.TZ_NY), 
                current_rsi
            )
            
            if res['signal_type']:
                spy_price = get_live_price("SPY")
                valid = False
                
                # --- OMNI-DIRECTIONAL LOGIC ---
                
                # CASE A: BULL FRACTAL (Calls)
                if res['signal_type'] == 'BULL_FRACTAL':
                    if SENTINEL_MODE in ["ALL", "CALLS"]:
                        if spy_price > orb_high: # Breakout UP
                            valid = True
                        else:
                            # Log blockage mostly for debugging
                            pass
                
                # CASE B: BEAR FRACTAL (Puts)
                elif res['signal_type'] == 'BEAR_FRACTAL':
                    if SENTINEL_MODE in ["ALL", "PUTS"]:
                        if spy_price < orb_low: # Breakout DOWN
                            valid = True
                        else:
                            pass

                if valid:
                    dispatch_alert(res, gatekeeper_note="ORB Breakout Confirmed")
                    time.sleep(600) # 10m Cooldown
                else:
                    time.sleep(30)

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt: sys.exit()
        except Exception as e:
            log.error(f"Sentinel Error: {e}")
            time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run_sentinel()