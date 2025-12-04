import sys
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

# Import Config (The Vault)
from src.utils import config
from src.utils.logger import get_logger
import src.core.strat_fractal as strat_fractal

# [NEW] Import Gatekeeper Engine
from src.core.engine_confirmation import ConfirmationEngine

log = get_logger("Sentinel")
SCAN_INTERVAL = 60 

# ==============================================================================
# 1. MARKET DATA (THE GLASS FEED)
# ==============================================================================
def fetch_live_vix():
    """Fetches VIX data for Fractal Flow analysis."""
    try:
        vix_1h = yf.Ticker("^VIX").history(period="5d", interval="1h")
        vix_5m = yf.Ticker("^VIX").history(period="5d", interval="5m")

        if vix_1h.empty or vix_5m.empty: return None, None

        vix_1h.index = vix_1h.index.tz_convert(config.TZ_NY)
        vix_5m.index = vix_5m.index.tz_convert(config.TZ_NY)

        return vix_1h, vix_5m
    except Exception as e:
        log.error(f"Data Fetch Error: {e}")
        return None, None

def get_spy_price():
    try:
        data = yf.Ticker("SPY").history(period="1d", interval="1m")
        if not data.empty: return data['Close'].iloc[-1]
    except: pass
    return 0.0

# ==============================================================================
# 2. ALERTING SYSTEM
# ==============================================================================
def dispatch_alert(signal_data, gatekeeper_note=""):
    timestamp = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S")
    spy_price = get_spy_price()
    bias = signal_data.get('macro_trend')
    reason = signal_data.get('reason')
    
    # --- CONSOLE VISUAL ---
    print("\n" + "="*60)
    print(f"🚨 SENTINEL ALERT // {timestamp}")
    print(f"TYPE:    {bias}")
    print(f"REASON:  {reason}")
    print(f"CONFIRM: {gatekeeper_note}")
    print(f"CONTEXT: SPY ${spy_price:.2f}")
    print("="*60 + "\n")

    # --- DISCORD (Via Config) ---
    if config.ENABLE_DISCORD and "http" in config.DISCORD_WEBHOOK:
        color = 5763719 if "BEARISH VIX" in bias else 15158332
        payload = {
            "username": "Quant OS Sentinel",
            "embeds": [{
                "title": "🚨 FRACTAL FLOW TRIGGER",
                "color": color, 
                "fields": [
                    {"name": "Bias", "value": bias, "inline": True},
                    {"name": "SPY Price", "value": f"${spy_price:.2f}", "inline": True},
                    {"name": "Logic", "value": reason, "inline": False},
                    {"name": "Gatekeeper", "value": f"✅ {gatekeeper_note}", "inline": False},
                    {"name": "Time", "value": timestamp, "inline": False}
                ],
                "footer": {"text": "Quant OS v3.1 // Surgical Precision"}
            }]
        }
        try:
            requests.post(config.DISCORD_WEBHOOK, json=payload)
            print(">> Discord Webhook Dispatched.")
        except Exception as e:
            log.error(f"Discord Dispatch Failed: {e}")

# ==============================================================================
# 3. SENTINEL LOOP
# ==============================================================================
def run_sentinel():
    print("\n   SENTINEL v3.1 // SURGICAL WATCHTOWER")
    print("   ------------------------------------")
    if config.ENABLE_DISCORD: 
        print("   [✓] DISCORD LINK:  ACTIVE")
    else:              
        print("   [X] DISCORD LINK:  OFF (Check config.py)")
    
    # Initialize MTC Engine
    mtc = ConfirmationEngine("SPY")
    print("   [✓] MTC ENGINE:    ONLINE (Gatekeeper Active)")
    
    print("\n   [STATUS: ARMED & SCANNING]\n")
    
    while True:
        try:
            now_ny = datetime.now(config.TZ_NY)
            
            # --- HARD DECK (09:30 - 09:45 ET) ---
            market_open = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
            hard_deck = market_open + timedelta(minutes=15)
            
            # --- MARKET HOURS GUARD ---
            # Guard runs 06:00 to 17:00 ET (covers pre/post) on weekdays
            if now_ny.weekday() >= 5 or now_ny.hour < 6 or now_ny.hour >= 17:
                print(f"\r[SLEEP] Market Closed ({now_ny.strftime('%H:%M')})...", end="")
                time.sleep(300)
                continue

            if now_ny < hard_deck and now_ny >= market_open:
                wait_min = (hard_deck - now_ny).seconds // 60
                print(f"\r[HOLD] Hard Deck Active. Scanning starts in {wait_min}m...", end="")
                time.sleep(30)
                continue

            # --- SCAN ROUTINE ---
            print(f"\r[SCAN] Scanning VIX Structures @ {now_ny.strftime('%H:%M:%S')}...", end="")
            
            vix_1h_raw, vix_5m_raw = fetch_live_vix()
            
            if vix_1h_raw is not None and vix_5m_raw is not None:
                vix_1h = strat_fractal.calculate_macd(vix_1h_raw)
                vix_5m = strat_fractal.calculate_macd(vix_5m_raw)
                
                # 1. Check Fractal Strategy (The Signal)
                current_ts = pd.Timestamp.now(tz=config.TZ_NY)
                result = strat_fractal.check_fractal_flow(vix_1h, vix_5m, current_ts)
                
                if result['signal']:
                    # 2. Check Gatekeeper (The Confirmation)
                    print(f"\n[!] Signal Detected. Requesting MTC Validation...")
                    gatekeeper = mtc.validate_signal()
                    
                    if gatekeeper['valid']:
                        dispatch_alert(result, gatekeeper_note=gatekeeper['reason'])
                        time.sleep(300) # Cooldown to avoid spam
                    else:
                        print(f"🛑 BLOCKED by Gatekeeper: {gatekeeper['reason']}")
            
            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n🛑 Sentinel Deactivated.")
            sys.exit()
        except Exception as e:
            log.error(f"Sentinel Loop Error: {e}")
            time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run_sentinel()