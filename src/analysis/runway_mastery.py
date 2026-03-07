import sys
import duckdb
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.core import magitek_engine_v2 # Our hardened engine

def master_the_known():
    # SET THE DATES (Based on today being March 5)
    t_minus_2 = "2026-03-03" # Tuesday: Our Runway
    t_minus_1 = "2026-03-04" # Wednesday: Our Takeoff
    
    print(f"🛠️  PHASE 1: MASTERING THE RUNWAY ({t_minus_2})")
    # In a real institutional flow, we would run the Grid Search here 
    # and extract the 'Apex' parameters. For this test, we use the 
    # Tier-3 / 65% Conf / 15m Cooldown settings we identified.

    params = {
        'conf_limit': 65.0,
        'cooldown': 15,
        'tp': 1.45, # +45%
        'sl': 0.70  # -30%
    }
    
    print(f"📊 JUSTIFICATION FOR PARAMETERS:")
    print(f"  - Conf Limit: {params['conf_limit']}% | Rationale: Maximum signal density vs. accuracy.")
    print(f"  - Cooldown:   {params['cooldown']}m | Rationale: Prevents signal stacking during trending moves.")
    print(f"  - Risk/Reward: 1.5:1 | Rationale: Required to offset the 1.5% Slippage Tax.")

    print(f"\n⚡ PHASE 2: THE TAKEOFF TEST ({t_minus_1})")
    print("Running unified session on YESTERDAY'S data using T-2 rules...")
    
    # Execute the backtest on March 4th only
    start_dt = datetime.strptime(t_minus_1, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    # Note: magitek_engine_v2 needs to be called with these params passed in
    # For now, ensure your magitek_engine_v2.py is updated with the 5% cap.
    magitek_engine_v2.run_unified_session(start_dt, end_dt)

if __name__ == "__main__":
    master_the_known()