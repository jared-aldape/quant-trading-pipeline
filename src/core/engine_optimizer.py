import sys
import duckdb
import pandas as pd
import numpy as np
import json
import itertools
from pathlib import Path
from datetime import datetime, timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import strat_fractal

log = get_logger("Optimizer")
PARAMS_FILE = config.DATA_DIR / "strat_params.json"

# ==============================================================================
# 2. OPTIMIZATION LOGIC
# ==============================================================================
def run_optimization_cycle(lookback_days=30):
    """
    Analyzes VIX Regime to adapt Strategy Parameters.
    """
    log.info(f"🧬 Starting Evolutionary Optimization (Lookback: {lookback_days}d)...")
    
    if not config.DB_FILE.exists(): return
    
    # 1. Fetch VIX Data
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    try:
        vix = con.execute(f"""
            SELECT datetime_utc, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker='VIX' 
            AND datetime_utc >= '{start_date}' 
            ORDER BY datetime_utc ASC
        """).df()
    except Exception as e:
        log.error(f"Data Fetch Error: {e}")
        return
    finally:
        con.close()
    
    if vix.empty: 
        log.warning("⚠️ No VIX data found for optimization.")
        return

    # 2. Analyze VIX Regime
    current_vix = vix['close'].iloc[-1]
    avg_vix = vix['close'].mean()
    
    log.info(f"📊 Market Regime Analysis: Current VIX: {current_vix:.2f} | 30d Avg: {avg_vix:.2f}")

    # 3. Define Adaptive Parameters
    # Baseline Defaults
    new_params = {
        "macro_bearish_threshold": -0.05,
        "macro_bullish_threshold": 0.05,
        "rsi_call_limit": 70,
        "rsi_put_limit": 30
    }
    
    regime = "NORMAL"

    # --- HEURISTIC ADAPTATION LOGIC ---
    if current_vix > 22:
        # FEAR REGIME (High Volatility)
        # Market moves fast. Calls are risky (catching knives). Puts are expensive but pay off.
        regime = "HIGH_VOL (FEAR)"
        new_params['rsi_call_limit'] = 60   # Stricter: Only buy calls if DEEPLY oversold
        new_params['rsi_put_limit'] = 40    # Looser: Momentum Puts work well here
        new_params['macro_bearish_threshold'] = -0.08 # Require stronger trend for Calls
        
    elif current_vix < 12:
        # COMPLACENCY REGIME (Low Volatility)
        # Grind up. Puts are dangerous (Theta burn). Calls are safer.
        regime = "LOW_VOL (GRIND)"
        new_params['rsi_call_limit'] = 75   # Looser: Buy calls even if slightly overbought (momentum)
        new_params['rsi_put_limit'] = 20    # Stricter: Only buy puts if extreme spike
        new_params['macro_bullish_threshold'] = 0.08 # Require massive spike for Puts
        
    else:
        # NORMAL REGIME
        regime = "NORMAL"
        # Keep defaults

    log.info(f"🌊 Regime Detected: {regime}")
    log.info(f"🧬 Adapting DNA: {new_params}")

    # 4. Commit to Gene Pool
    try:
        with open(PARAMS_FILE, 'w') as f:
            json.dump(new_params, f, indent=4)
        log.info("✅ Strategy Parameters Updated.")
    except Exception as e:
        log.error(f"❌ Failed to save params: {e}")

if __name__ == "__main__":
    run_optimization_cycle()