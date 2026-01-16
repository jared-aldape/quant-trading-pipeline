import sys
import duckdb
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("Optimizer")
PARAMS_FILE = ROOT_DIR / "data" / "strat_params.json"

# ==============================================================================
# 2. ADAPTIVE LOGIC (VIX SCALAR)
# ==============================================================================
def save_params(params):
    try:
        with open(PARAMS_FILE, 'w') as f:
            json.dump(params, f, indent=4)
        log.info(f"💾 Optimized Strategy Params: {json.dumps(params)}")
    except Exception as e:
        log.error(f"Failed to save parameters: {e}")

def run_optimization_cycle():
    log.info("⚔️ STARTING ADAPTIVE WARFARE CYCLE (VIX Scalar)")
    
    try:
        if not config.DB_FILE.exists():
            log.warning("❌ DB Not Found. Skipping.")
            return

        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. GET MARKET CONTEXT (VIX LEVEL)
        try:
            # Get latest VIX close
            vix_now = con.execute(f"SELECT close FROM {config.TBL_INDICES} WHERE ticker='VIX' ORDER BY datetime_utc DESC LIMIT 1").fetchone()[0]
        except:
            vix_now = 15.0 # Default
            
        # 2. GET TREND BIAS
        bias_strength = 0.5
        bias_dir = "NEUTRAL"
        
        try:
            q = f"SELECT trade_type FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC LIMIT 50"
            recent_trades = con.execute(q).df()
            if not recent_trades.empty:
                total = len(recent_trades)
                calls = len(recent_trades[recent_trades['trade_type'] == 'CALL'])
                puts = len(recent_trades[recent_trades['trade_type'] == 'PUT'])
                bias_strength = max(calls, puts) / total
                bias_dir = "BULL" if calls > puts else "BEAR"
        except: pass
        
        con.close()

        log.info(f"📊 MARKET STATE: VIX={vix_now:.2f} | Trend={bias_dir} ({bias_strength:.0%})")

        # 3. CALCULATE PARAMETERS
        # Base: Standard 20/80
        rsi_floor = 20
        rsi_ceil = 80
        regime = "NORMAL"
        alloc = 1.0

        # SCENARIO A: LOW VOLATILITY (VIX < 14)
        # Market is compressed. Signals are smaller. We must WIDEN the net.
        if vix_now < 14.0:
            regime = "LOW_VOL_COMPRESSION"
            rsi_floor = 35 # Easier to hit oversold
            rsi_ceil = 65  # Easier to hit overbought
            alloc = 0.5    # Lower size (whipsaw risk)
        
        # SCENARIO B: HIGH VOLATILITY (VIX > 22)
        # Market is wild. RSI extremes are common. TIGHTEN the net.
        elif vix_now > 22.0:
            regime = "HIGH_VOL_CRISIS"
            rsi_floor = 10 # Only take extreme oversold
            rsi_ceil = 90  # Only take extreme overbought
            alloc = 1.0

        # SCENARIO C: STRONG TREND (Bias > 75%)
        # Don't fade the trend. Join it.
        elif bias_strength > 0.75:
            regime = f"STRONG_{bias_dir}_TREND"
            if bias_dir == "BULL":
                rsi_floor = 40 # Buy dips early
                rsi_ceil = 85  # Let it run
            else:
                rsi_floor = 15
                rsi_ceil = 60 # Short rips early
            alloc = 1.5

        new_params = {
            "last_updated": datetime.now().isoformat(),
            "regime": regime,
            "rsi_floor": rsi_floor,
            "rsi_ceil": rsi_ceil,
            "allocation": alloc
        }
        
        save_params(new_params)

    except Exception as e:
        log.error(f"Optimizer Crash: {e}")

if __name__ == "__main__":
    run_optimization_cycle()