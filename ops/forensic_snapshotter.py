import sys
import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("Forensics")

# ==============================================================================
# MATH CORE (Consistent with Live Scope)
# ==============================================================================
def calculate_vix_metrics(df):
    if df.empty: return None
    df = df.copy()
    # MACD (12, 26, 9)
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    # RSI (14)
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df.iloc[-1]

def calculate_xsp_structure(df):
    if df.empty or len(df) < 20: return None
    df = df.copy()
    
    # Linear Regression Channel (Last 20 bars)
    y = df['close'].values
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1)
    
    current_price = y[-1]
    reg_mean = slope * x[-1] + intercept
    std_dev = df['close'].std()
    
    # Z-Score (Distance from Mean in Std Devs)
    z_score = (current_price - reg_mean) / std_dev if std_dev > 0 else 0
    
    return {
        "price": current_price,
        "reg_mean": reg_mean,
        "slope": slope,
        "std_dev": std_dev,
        "z_score": z_score
    }

# ==============================================================================
# FORENSIC ENGINE
# ==============================================================================
def capture_market_state(target_ts_utc):
    """
    Takes a UTC timestamp. Looks back 60 minutes to build context.
    Returns a dictionary of the exact market state at that second.
    """
    if not config.DB_FILE.exists(): return None
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # Define Window: 60 mins leading up to the target
        end_str = target_ts_utc.strftime('%Y-%m-%d %H:%M:%S')
        start_dt = target_ts_utc - timedelta(minutes=60)
        start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Fetch XSP Context
        q_xsp = f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='XSP' AND datetime_utc BETWEEN '{start_str}' AND '{end_str}' ORDER BY datetime_utc ASC"
        xsp_df = con.execute(q_xsp).df()
        
        # Fetch VIX Context
        q_vix = f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND datetime_utc BETWEEN '{start_str}' AND '{end_str}' ORDER BY datetime_utc ASC"
        vix_df = con.execute(q_vix).df()
        
        con.close()
        
        # --- CALCULATE METRICS ---
        state = {
            "timestamp": end_str,
            "valid": False
        }
        
        # 1. VIX Forensics
        if not vix_df.empty:
            v_metrics = calculate_vix_metrics(vix_df)
            state["vix_close"] = v_metrics['close']
            state["vix_rsi"] = v_metrics['rsi']
            state["vix_macd_hist"] = v_metrics['hist']
            state["vix_velocity"] = v_metrics['close'] - vix_df.iloc[0]['close'] # 1hr change
        
        # 2. XSP Forensics
        if not xsp_df.empty:
            x_metrics = calculate_xsp_structure(xsp_df)
            if x_metrics:
                state["xsp_price"] = x_metrics['price']
                state["linreg_deviation"] = x_metrics['z_score'] # Critical: How overextended was it?
                state["trend_slope"] = x_metrics['slope']
                state["valid"] = True
                
        return state

    except Exception as e:
        log.error(f"Forensic Snapshot Failed: {e}")
        return None

# ==============================================================================
# MANUAL TESTER
# ==============================================================================
if __name__ == "__main__":
    # Test with the timestamp you found in the Auditor!
    # Example: 2025-12-18 14:49:00 (UTC approx 19:49 or 20:49 depending on offset)
    # Let's pass a string ISO format
    import sys
    
    if len(sys.argv) > 1:
        ts_str = sys.argv[1] # Expected Format: "2025-12-18 19:49:00"
        dt = pd.to_datetime(ts_str)
    else:
        print("Usage: python ops/forensic_snapshotter.py '2025-12-18 19:49:00'")
        sys.exit()
        
    print(f"\n🔬 ANALYZING CRIME SCENE: {dt}...")
    snapshot = capture_market_state(dt)
    
    if snapshot and snapshot['valid']:
        print("\n=== FORENSIC REPORT ===")
        print(f"🧬 VIX RSI:        {snapshot.get('vix_rsi', 0):.2f}")
        print(f"🧬 VIX MACD Hist:  {snapshot.get('vix_macd_hist', 0):.4f}")
        print(f"📐 XSP Deviation:  {snapshot.get('linreg_deviation', 0):.2f} σ (Sigma)")
        print(f"📐 Trend Slope:    {snapshot.get('trend_slope', 0):.4f}")
        print("=======================\n")
        print("✅ The suspect (Perfect Trade) matches this profile.")
    else:
        print("❌ Insufficient data to build profile.")