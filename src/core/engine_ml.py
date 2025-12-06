import sys
import duckdb
import pandas as pd
import numpy as np
import json
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("MLEngine")
MODEL_FILE = config.DATA_DIR / "oracle_model.json"

# ==============================================================================
# 2. DATA INGESTION (The Training Gym)
# ==============================================================================
def fetch_training_data():
    """
    Fetches historical trade logs + VIX metrics.
    """
    if not config.DB_FILE.exists(): return pd.DataFrame()
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        # 1. Fetch Trade Outcomes (Target Variable)
        # We need trade result (Win/Loss) and timestamp
        trades = con.execute(f"""
            SELECT entry_time, type, return_pct 
            FROM {config.TBL_SIM_LOG}
            WHERE return_pct IS NOT NULL
        """).df()
        
        if trades.empty: return pd.DataFrame()
        
        # 2. Fetch VIX Metrics (Features)
        vix = con.execute(f"""
            SELECT datetime_utc, close as vix_close
            FROM {config.TBL_INDICES}
            WHERE ticker = 'VIX'
        """).df()
        
        # CRITICAL FIX: Standardize VIX to UTC Aware
        vix['datetime_utc'] = pd.to_datetime(vix['datetime_utc'])
        if vix['datetime_utc'].dt.tz is None:
            vix['datetime_utc'] = vix['datetime_utc'].dt.tz_localize('UTC')
        else:
            vix['datetime_utc'] = vix['datetime_utc'].dt.tz_convert('UTC')
            
        # 3. Merge (AsOf Join)
        # Trades are in Local Time usually in SIM_LOG, need conversion
        trades['entry_time'] = pd.to_datetime(trades['entry_time'])
        if trades['entry_time'].dt.tz is None:
             trades['entry_time'] = trades['entry_time'].dt.tz_localize(config.TZ_LOCAL)
        
        trades['entry_time_utc'] = trades['entry_time'].dt.tz_convert('UTC')
        
        # Sort for merge_asof
        trades = trades.sort_values('entry_time_utc')
        vix = vix.sort_values('datetime_utc')
        
        merged = pd.merge_asof(
            trades, vix, 
            left_on='entry_time_utc', 
            right_on='datetime_utc',
            direction='backward'
        )
        
        # 4. Feature Engineering
        merged['is_win'] = (merged['return_pct'] > 0).astype(int)
        merged['hour'] = merged['entry_time'].dt.hour
        
        # Add RSI manually if not in DB (simplified for now)
        # Ideally VIX RSI should be pre-calculated in DB
        merged['vix_rsi'] = 50.0 # Placeholder if column missing
        
        return merged[['type', 'vix_close', 'vix_rsi', 'hour', 'is_win']]
        
    except Exception as e:
        log.error(f"ML Data Fetch Error: {e}")
        return pd.DataFrame()
    finally:
        con.close()

# ==============================================================================
# 3. MODEL OPERATIONS (The Oracle)
# ==============================================================================
def train_oracle():
    """Trains the Random Forest model."""
    df = fetch_training_data()
    if df.empty or len(df) < 50:
        log.warning("⚠️ Insufficient data to train Oracle.")
        return
        
    log.info(f"🧠 Training Oracle on {len(df)} samples...")
    
    # Encode 'type' (Call=1, Put=0)
    df['type_code'] = np.where(df['type'] == 'CALL', 1, 0)
    
    X = df[['type_code', 'vix_close', 'hour']] # Add 'vix_rsi' when ready
    y = df['is_win']
    
    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    model.fit(X, y)
    
    # Save Weights (Mock JSON for now, normally Pickle/Joblib)
    # We save feature importance to understand logic
    importance = dict(zip(X.columns, model.feature_importances_))
    
    # In a real deployment, use joblib.dump(model, 'oracle.pkl')
    # For this architecture, we just log the success
    log.info(f"✅ Oracle Trained. Feature Importance: {importance}")
    return model

def predict_success(signal_type, vix_val, vix_rsi, hour=10):
    """
    Returns probability of success (0-100).
    Mock logic if model not loaded.
    """
    # Heuristic Fallback (until enough training data)
    base_score = 50
    
    if signal_type == "CALL":
        if vix_val < 20: base_score += 10
        if vix_rsi < 30: base_score += 20 # Oversold bounce
    else: # PUT
        if vix_val > 25: base_score += 10
        if vix_rsi > 70: base_score += 20 # Overbought crush
        
    return min(95, max(5, base_score))

if __name__ == "__main__":
    train_oracle()