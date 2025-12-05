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
from src.core.engine_confirmation import ConfirmationEngine

log = get_logger("Sentinel")
SCAN_INTERVAL = 60 

# ==============================================================================
# 1. ORB INTELLIGENCE (Project Echo)
# ==============================================================================
def get_orb_levels(ticker="SPY"):
    """
    Calculates the 30-minute Opening Range Breakout (ORB) levels.
    Returns: (orb_high, orb_low) or (None, None) if not yet 10:00 ET.
    """
    now_ny = datetime.now(config.TZ_NY)
    today_str = now_ny.strftime('%Y-%m-%d')
    
    # Define ORB Window: 09:30 - 10:00 ET
    orb_start = config.TZ_NY.localize(datetime.combine(now_ny.date(), dtime(9, 30)))
    orb_end = config.TZ_NY.localize(datetime.combine(now_ny.date(), dtime(10, 0)))
    
    if now_ny < orb_end:
        return None, None # Still forming
        
    try:
        # Fetch 1m data for today
        df = yf.Ticker(ticker).history(start=today_str, interval="1m")
        if df.empty: return None, None
        
        # Localize if needed
        if df.index.tz is None:
            df.index = df.index.tz_localize(config.TZ_NY)
        else:
            df.index = df.index.tz_convert(config.TZ_NY)
            
        # Filter for the first 30 mins
        orb_df = df[(df.index >= orb_start) & (df.index < orb_end)]
        
        if orb_df.empty: return None, None
        
        orb_high = orb_df['High'].max()
        orb_low = orb_df['Low'].min()
        
        return orb_high, orb_low
        
    except Exception as e:
        log.error(f"ORB Calc Failed: {e}")
        return None, None

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
# 3. ALERTING SYSTEM
# ==============================================================================
def dispatch_alert(signal_data, gatekeeper_note="", orb_status=""):
    timestamp = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S")
    spy_price = get_live_price("SPY")
    bias = signal_data.get('signal_type', 'NEUTRAL') # Fixed key access
    reason = signal_data.get('reason')
    
    print("\n" + "="*60)
    print(f"🚨 SENTINEL ALERT // {timestamp}")
    print(f"TYPE:    {bias}")
    print(f"CONTEXT: SPY ${spy_price:.2f} | {orb_status}")
    print(f"LOGIC:   {reason}")
    print(f"GATE:    {gatekeeper_note}")
    print("="*60 + "\n")

    if config.ENABLE_DISCORD and "http" in config.DISCORD_WEBHOOK:
        color = 15158332 if "SHORT" in bias or "PUT" in bias else 5763719
        payload = {
            "username": "Quant OS Sentinel",
            "embeds": [{
                "title": f"🚨 {bias} DETECTED",
                "color": color, 
                "fields": [
                    {"name": "SPY Price", "value": f"${spy_price:.2f}", "inline": True},
                    {"name": "ORB Status", "value": orb_status, "inline": True},
                    {"name": "Logic", "value": reason, "inline": False},
                    {"name": "Gatekeeper", "value": f"✅ {gatekeeper_note}", "inline": False},
                    {"name": "Time", "value": timestamp, "inline": False}
                ],
                "footer": {"text": "Quant OS v3.2 // Project Echo"}
            }]
        }
        try:
            requests.post(config.DISCORD_WEBHOOK, json=payload)
        except: pass

# ==============================================================================
# 4. SENTINEL LOOP
# ==============================================================================
def run_sentinel():
    print("\n   SENTINEL v3.2 // PROJECT ECHO ACTIVE")
    print("   ------------------------------------")
    mtc = ConfirmationEngine("SPY")
    print("   [✓] GATEKEEPER:    ONLINE")
    
    orb_high, orb_low = None, None
    print("   [✓] ORB MONITOR:   ARMED (09:30 - 10:00 ET)")
    
    while True:
        try:
            now_ny = datetime.now(config.TZ_NY)
            current_time = now_ny.time()
            
            # --- MARKET HOURS GUARD (09:30 - 16:00 ET) ---
            if now_ny.weekday() >= 5 or current_time < dtime(9, 30) or current_time >= dtime(16, 0):
                print(f"\r[SLEEP] Market Closed ({now_ny.strftime('%H:%M')})...", end="")
                time.sleep(300)
                continue

            # --- ORB FORMATION PHASE (09:30 - 10:00) ---
            if current_time < dtime(10, 0):
                print(f"\r[OBSERVE] Forming Opening Range (Ends 10:00 ET)... SPY: ${get_live_price():.2f}", end="")
                time.sleep(30)
                continue
            
            # --- ORB CALCULATION (Once per day logic) ---
            if orb_high is None:
                orb_high, orb_low = get_orb_levels("SPY")
                if orb_high:
                    print(f"\n[🔒] ORB LOCKED: High ${orb_high:.2f} | Low ${orb_low:.2f}")
                else:
                    print(f"\r[WAIT] Waiting for data...", end="")
                    time.sleep(10)
                    continue

            # --- SCANNING PHASE ---
            print(f"\r[SCAN] VIX Structures... SPY: ${get_live_price():.2f}", end="")
            
            vix_1h, vix_5m = fetch_live_vix()
            if vix_1h is None: continue
            
            # 1. Fractal Check
            # Get latest RSI for Gatekeeper Law
            current_rsi = strat_fractal.calculate_rsi(vix_5m).iloc[-1]['rsi']
            
            res = strat_fractal.check_fractal_flow(
                strat_fractal.calculate_macd(vix_1h),
                strat_fractal.calculate_macd(vix_5m),
                pd.Timestamp.now(tz=config.TZ_NY),
                current_rsi
            )
            
            if res['signal_type']:
                spy_price = get_live_price("SPY")
                orb_status = "INSIDE CHOP"
                is_valid_orb = False
                
                # 2. ORB FILTER (Project Echo)
                if res['signal_type'] == 'call':
                    if spy_price > orb_high:
                        orb_status = "✅ BREAKOUT (Above ORB High)"
                        is_valid_orb = True
                    else:
                        orb_status = "🛑 BLOCKED (Below ORB High)"
                
                elif res['signal_type'] == 'put':
                    if spy_price < orb_low:
                        orb_status = "✅ BREAKDOWN (Below ORB Low)"
                        is_valid_orb = True
                    else:
                        orb_status = "🛑 BLOCKED (Above ORB Low)"

                # 3. FINAL DISPATCH
                if is_valid_orb:
                    print(f"\n[!] ORB CONFIRMED. Requesting MTC...")
                    # Optional: Add extra MTC check here if desired
                    dispatch_alert(res, gatekeeper_note="ORB Validated", orb_status=orb_status)
                    time.sleep(300) # Cooldown
                else:
                    print(f"\n[🛡️] ECHO GUARD: Signal {res['signal_type']} blocked. {orb_status}")
                    time.sleep(60)

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n🛑 Sentinel Deactivated.")
            sys.exit()
        except Exception as e:
            log.error(f"Sentinel Loop Error: {e}")
            time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run_sentinel()