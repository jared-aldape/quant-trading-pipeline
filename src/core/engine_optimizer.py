import sys
import duckdb
import pandas as pd
import numpy as np
import json
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
except ImportError:
    print("❌ CRITICAL: Could not import 'src.utils'.")
    sys.exit(1)

log = get_logger("Optimizer")

# ==============================================================================
# 2. ADAPTIVE LOGIC (The Brain)
# ==============================================================================
def run_optimization_cycle():
    """
    Analyzes the Trade Manifest and recommends parameter adjustments.
    DOES NOT DELETE DATA.
    """
    log.info("⚔️ STARTING ADAPTIVE WARFARE CYCLE (Evolutionary Optimizer)")
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. SAFETY CHECK: Ensure Manifest Exists
        table_check = con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{config.TBL_MANIFEST}'").fetchone()[0]
        if table_check == 0:
            log.warning(f"⚠️ Manifest table '{config.TBL_MANIFEST}' not found. Skipping optimization.")
            con.close()
            return

        # 2. FETCH RECENT PERFORMANCE
        # We look at the last 20 trades to determine current "Regime"
        query = f"""
            SELECT trade_type, date, entry_timestamp_utc
            FROM {config.TBL_MANIFEST}
            ORDER BY entry_timestamp_utc DESC
            LIMIT 20
        """
        recent_trades = con.execute(query).df()
        
        # 3. ANALYZE REGIME
        if recent_trades.empty:
            log.info("ℹ️ No recent trades to analyze. Keeping default parameters.")
            con.close()
            return

        total_count = len(recent_trades)
        call_count = len(recent_trades[recent_trades['trade_type'].str.lower() == 'call'])
        put_count = len(recent_trades[recent_trades['trade_type'].str.lower() == 'put'])
        
        # Calculate Bias Strength
        # If > 70% of signals are ONE side, we are in a strong trend.
        bias_strength = max(call_count, put_count) / total_count if total_count > 0 else 0
        
        log.info(f"📊 OPTIMIZER REPORT (Last {total_count} trades):")
        log.info(f"   Calls: {call_count} | Puts: {put_count}")
        log.info(f"   Trend Bias: {bias_strength:.1%} ")

        # 4. EVOLUTIONARY LOGIC (Recommend Updates)
        # This is where we would update strat_params.json
        if bias_strength > 0.75:
            log.info("🚀 REGIME DETECTED: Momentum Trend. Recommending 'AGGRESSIVE' Mode.")
            # Code to update JSON config would go here
        elif bias_strength < 0.55:
            log.info("⚖️ REGIME DETECTED: Choppy/Neutral. Recommending 'DEFENSIVE' Mode.")
        else:
            log.info("✅ REGIME DETECTED: Balanced. Maintaining Standard Protocols.")

        con.close()
        log.info("✅ Optimization Cycle Complete.")
        
    except Exception as e:
        log.error(f"❌ OPTIMIZER FAILURE: {e}")

if __name__ == "__main__":
    run_optimization_cycle()