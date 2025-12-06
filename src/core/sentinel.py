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
from src.core import engine_simulator

log = get_logger("Sentinel")
SCAN_INTERVAL = 60 

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
# 3. RISK MANAGEMENT (CIRCUIT BREAKER)
# ==============================================================================
def check_circuit_breaker():
    """
    Monitors Daily PnL. Triggers LIQUIDATION if limit breached.
    """
    stats = engine_simulator.get_portfolio_stats()
    current_pnl_pct = stats.get('pnl_pct', 0.0)
    
    if current_pnl_pct <= -5.0: # Hardcoded 5% limit if config missing
        limit = getattr(config, 'RISK_MAX_DAILY_LOSS_PCT', 5.0)
        if current_pnl_pct <= -limit:
            dispatch_alert({"signal_type": "MAYDAY", "reason": f"Daily Loss {current_pnl_pct:.2f}% exceeds limit"}, "CIRCUIT BREAKER TRIGGERED")
            
            session = engine_simulator.load_session()
            positions = session.get('positions', [])
            
            if positions:
                print(f"\n[💀] CIRCUIT BREAKER: LIQUIDATING {len(positions)} POSITIONS...")
                for p in positions:
                    res = engine_simulator.execute_exit(p['trade_id'], reason="CIRCUIT_BREAKER")
                    print(f"    -> {res}")
                return True
            
    return False

# ==============================================================================
# 4. ALERTING
# ==============================================================================
def dispatch_alert(signal_data, gatekeeper_note="", orb_status=""):
    timestamp = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S")
    spy_price = get_live_price("SPY")
    bias = signal_data.get('signal_type', 'NEUTRAL') 
    
    print("\n" + "="*60)
    print(f"🚨 SENTINEL ALERT // {timestamp}")
    print(f"TYPE:    {bias}")
    print(f"STATUS:  {gatekeeper_note}")
    print("="*60 + "\n")

    if config.ENABLE_DISCORD and "http" in config.DISCORD_WEBHOOK:
        color = 15548997 if "MAYDAY" in bias else 5763719
        payload = {
            "username": "Quant OS Sentinel",
            "embeds": [{
                "title": f"🚨 {bias}",
                "color": color, 
                "fields": [
                    {"name": "SPY Price", "value": f"${spy_price:.2f}", "inline": True},
                    {"name": "Note", "value": gatekeeper_note, "inline": False},
                    {"name": "Logic", "value": signal_data.get('reason', 'N/A'), "inline": False}
                ],
                "footer": {"text": f"Quant OS v3.3"}
            }]
        }
        try: requests.post(config.DISCORD_WEBHOOK, json=payload)
        except: pass

# ==============================================================================
# 5. MAIN LOOP
# ==============================================================================
def run_sentinel():
    print(f"\n   SENTINEL v3.3 // TACTICAL COMMAND ACTIVE")
    limit = getattr(config, 'RISK_MAX_DAILY_LOSS_PCT', 5.0)
    print(f"   [🛡️] CIRCUIT BREAKER: ARMED (-{limit}%)")
    print(f"   [✓] ORB MONITOR:     ARMED ({config.ORB_WINDOW_MINUTES}m)")
    
    orb_high, orb_low = None, None
    orb_end_time = (datetime.combine(datetime.today(), dtime(9, 30)) + timedelta(minutes=config.ORB_WINDOW_MINUTES)).time()
    
    while True:
        try:
            now_ny = datetime.now(config.TZ_NY)
            current_time = now_ny.time()
            
            # --- MARKET HOURS GUARD ---
            if now_ny.weekday() >= 5 or current_time < dtime(9, 30) or current_time >= dtime(16, 0):
                print(f"\r[SLEEP] Market Closed ({now_ny.strftime('%H:%M')})...", end="")
                time.sleep(300)
                continue

            # --- CIRCUIT BREAKER CHECK ---
            if check_circuit_breaker():
                print("\n[💀] SYSTEM LOCKDOWN. Manual Reset Required.")
                time.sleep(3600)
                continue

            # --- ORB PHASE ---
            if current_time < orb_end_time:
                print(f"\r[OBSERVE] Forming ORB (Ends {orb_end_time.strftime('%H:%M')} ET)... SPY: ${get_live_price():.2f}", end="")
                time.sleep(30)
                continue
            
            if orb_high is None:
                orb_high, orb_low = get_orb_levels("SPY")
                if orb_high: print(f"\n[🔒] ORB LOCKED: {orb_high:.2f} | {orb_low:.2f}")
                else: 
                    time.sleep(10)
                    continue

            # --- SCAN PHASE ---
            print(f"\r[SCAN] VIX Structures... SPY: ${get_live_price():.2f}", end="")
            
            vix_1h, vix_5m = fetch_live_vix()
            if vix_1h is None: continue
            
            current_rsi = strat_fractal.calculate_rsi(vix_5m).iloc[-1]['rsi']
            res = strat_fractal.check_fractal_flow(
                strat_fractal.calculate_macd(vix_1h),
                strat_fractal.calculate_macd(vix_5m),
                pd.Timestamp.now(tz=config.TZ_NY),
                current_rsi
            )
            
            if res['signal_type']:
                spy_price = get_live_price("SPY")
                valid = False
                
                if res['signal_type'] == 'call' and spy_price > orb_high: valid = True
                elif res['signal_type'] == 'put' and spy_price < orb_low: valid = True

                if valid:
                    print(f"\n[!] SIGNAL CONFIRMED.")
                    dispatch_alert(res, gatekeeper_note="ORB Breakout Confirmed")
                    time.sleep(300)
                else:
                    print(f"\n[🛡️] ECHO GUARD: Signal blocked by ORB.")
                    time.sleep(60)

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt: sys.exit()
        except Exception as e:
            log.error(f"Sentinel Error: {e}")
            time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run_sentinel()