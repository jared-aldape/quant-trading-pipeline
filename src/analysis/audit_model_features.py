import sys
import duckdb
import joblib
import pandas as pd
import numpy as np
import pytz
from pathlib import Path

# ==============================================================================
# 1. PATH & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("AlphaMiner")

# TARGET THE V5 MODEL (True Win Architecture)
MODEL_PATH = config.DATA_DIR / "oracle_v5_precision.joblib"
TBL_SIM_LOG = getattr(config, 'TBL_SIM_LOG', 'active_simulation_log')

# THE V5 FEATURE SET
FEATURE_NAMES = [
    'Call/Put Bias', 'VIX MACD Hist', 'VIX MACD Cross', 'VIX RSI',
    'XSP MACD Hist', 'XSP MACD Cross', 'XSP ADX', 'Hour of Day'
]

# ==============================================================================
# 2. INSIGHT EXTRACTION ENGINE
# ==============================================================================
def mine_golden_rules():
    print("\n" + "="*80)
    log.info("🕵️ INITIATING ALPHA MINER (Extracting True-Win Overlaps...)")
    print("="*80)

    # ---------------------------------------------------------
    # PART A: THE ORACLE'S BRAIN (Feature Importance)
    # ---------------------------------------------------------
    if not MODEL_PATH.exists():
        log.error("❌ Oracle V5 not found. Run engine_ml_precision.py first.")
        return

    try:
        model = joblib.load(MODEL_PATH)
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        print("\n🧠 THE ORACLE'S FOCUS (What drove the decisions?)")
        print("-" * 60)
        
        for f in range(len(importances)):
            idx = indices[f]
            name = FEATURE_NAMES[idx] if idx < len(FEATURE_NAMES) else f"Feature {idx}"
            score = importances[idx] * 100
            print(f"   {f+1}. {name:<25} : {score:.2f}%")
            
    except Exception as e:
        log.error(f"Failed to read model: {e}")
        return

    # ---------------------------------------------------------
    # PART B: THE EMPIRICAL TRUTH (Data Overlap Mining)
    # ---------------------------------------------------------
    if not config.DB_FILE.exists():
        log.error("❌ Database not found for empirical mining.")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        q = f"SELECT * FROM {TBL_SIM_LOG} WHERE status = 'WIN' OR reason = 'TARGET_30_PCT'"
        wins = con.execute(q).df()
        con.close()
        
        if wins.empty:
            print("\n⚠️ No True Wins (+30% Target) found in the database yet.")
            return
            
        # --- TIMEZONE AND DATE RANGE CALCULATIONS ---
        wins['entry_time'] = pd.to_datetime(wins['entry_time'])
        wins['exit_time'] = pd.to_datetime(wins['exit_time'])
        
        # ⚡ FIX: Make BOTH times timezone-aware (UTC) before math
        if wins['entry_time'].dt.tz is None:
            wins['entry_time'] = wins['entry_time'].dt.tz_localize('UTC')
        if wins['exit_time'].dt.tz is None:
            wins['exit_time'] = wins['exit_time'].dt.tz_localize('UTC')
            
        wins['local_time'] = wins['entry_time'].dt.tz_convert('US/Pacific')
        
        start_date = wins['local_time'].min().strftime('%Y-%m-%d')
        end_date = wins['local_time'].max().strftime('%Y-%m-%d')
        unique_days = wins['local_time'].dt.date.nunique()
        total_wins = len(wins)
        avg_per_day = total_wins / unique_days if unique_days > 0 else 0
        
        print(f"\n🎯 MINING {total_wins} CONFIRMED TRUE WINS (+30% ROI)")
        print("-" * 60)
        
        print("📜 STRATEGY ASSUMPTIONS (Hardcoded in Simulator):")
        print("   1. Strike Selection: Exactly +1 Strike Out-Of-The-Money (OTM) from the XSP index price.")
        print("   2. Time of Purchase: The exact minute the VIX/RSI Fractal Signal fired.")
        print("   3. Target Execution: Hard limit order filled the moment the premium ticked to Entry + 30%.")
        
        print("\n📅 DATA RANGE & VOLUME:")
        print(f"   - Analysis Window: {start_date} to {end_date} ({unique_days} active trading days)")
        print(f"   - Average True Wins per Day: {avg_per_day:.1f}")
        
        # 1. DURATION OVERLAP
        wins['duration_mins'] = (wins['exit_time'] - wins['entry_time']).dt.total_seconds() / 60.0
        
        print("\n⏱️  DURATION DYNAMICS:")
        print(f"   - Average Time to +30%: {wins['duration_mins'].mean():.1f} minutes")
        print(f"   - Fastest +30% Strike:  {wins['duration_mins'].min():.1f} minutes")
        
        # 2. TEMPORAL OVERLAP (Localized to PST)
        wins['hour'] = wins['local_time'].dt.hour
        top_hour = wins['hour'].mode()[0]
        hour_pct = (len(wins[wins['hour'] == top_hour]) / len(wins)) * 100
        
        # Format for human reading (e.g., 07:00 AM)
        display_hour = pd.to_datetime(f"{int(top_hour)}:00", format='%H:%M').strftime('%I:%M %p')
        
        print("\n⏳ TEMPORAL OVERLAPS (PST):")
        print(f"   - The 'Golden Hour': {display_hour} PST")
        print(f"   - {hour_pct:.1f}% of all 30%+ wins occurred in this specific hour.")
        
        # 3. DIRECTIONAL BIAS
        calls = len(wins[wins['ticker'].str.contains('C')])
        print("\n📈 DIRECTIONAL BIAS:")
        print(f"   - CALL Wins: {(calls/total_wins)*100:.1f}% | PUT Wins: {((total_wins-calls)/total_wins)*100:.1f}%")
        
        # 4. ENTRY PREMIUM "SWEET SPOT"
        print("\n💰 PREMIUM SWEET SPOT:")
        print(f"   - The most common entry premium for a successful run was: ${wins['entry_price'].mean():.2f}")

        print("\n" + "="*80)
        log.info("✅ EMPIRICAL MINING COMPLETE.")
        print("="*80 + "\n")

    except Exception as e:
        log.error(f"Failed to mine empirical data: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    mine_golden_rules()