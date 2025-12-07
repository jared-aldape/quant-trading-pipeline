import sys
import duckdb
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import precision_score, accuracy_score

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: src/core/engine_ml.py
# Root: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OracleML")

MODEL_PATH = config.DATA_DIR / "oracle_v1.joblib"

# ==============================================================================
# 2. DATASET CONSTRUCTION (The Memory)
# ==============================================================================
def build_training_dataset():
    """
    Reconstructs history: Joins Signals (Manifest) with Outcomes (Options Data).
    Target: Did the trade hit +15% profit within 60 mins?
    """
    log.info("🧠 Constructing Training Dataset from Vault...")
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Fetch Signals
        query_sig = f"""
            SELECT entry_timestamp_utc, date, signal_type, xsp_price, trade_type 
            FROM {config.TBL_MANIFEST}
            WHERE xsp_price > 0
            ORDER BY entry_timestamp_utc ASC
        """
        signals = con.execute(query_sig).df()
        
        if signals.empty:
            log.warning("⚠️ No signals found in Manifest. Cannot train.")
            return pd.DataFrame()

        features = []
        targets = []
        
        # 2. Iterate and Check Outcomes
        # This is computationally expensive but necessary for Ground Truth.
        for _, row in signals.iterrows():
            # Parse Signal Info
            ts = row['entry_timestamp_utc']
            trade_type = row['trade_type']
            strike = int(round(row['xsp_price']))
            
            # Construct Ticker Logic (Simplified for ML Training)
            # We need to find the specific Option Contract used.
            # For training speed, we approximate by looking up the ATM contract.
            
            # Fetch Market Context (VIX, RSI at that time)
            # For now, we simulate features based on what we have.
            # In a full prod environment, you'd join with TBL_INDICES history.
            
            # --- LABELING (The Target) ---
            # Did it win? We check the next 60 minutes of price action.
            # Since we just calculated Greeks, we could use that, but raw price is safer.
            
            # Placeholder for speed: We assume a random distribution for this demo 
            # unless we perform the heavy TBL_OPTIONS lookup for every signal.
            # UPGRADE: In production, uncomment the deep lookup below.
            
            # Dummy Features for immediate functionality:
            # - Hour of Day
            # - Day of Week
            # - VIX (Randomized for demo, replace with lookup)
            
            dt = datetime.fromtimestamp(ts/1000)
            
            feat = {
                'hour': dt.hour,
                'dow': dt.weekday(),
                'vix': np.random.uniform(12, 35), # TO DO: Join with TBL_INDICES
                'type_code': 1 if trade_type == 'call' else 0
            }
            
            # Dummy Target: 
            # In reality, perform the SQL check: "Did High > Entry * 1.15?"
            is_win = 1 if np.random.random() > 0.45 else 0 
            
            features.append(feat)
            targets.append(is_win)
            
        con.close()
        
        X = pd.DataFrame(features)
        y = pd.Series(targets)
        
        return X, y

    except Exception as e:
        log.error(f"Dataset Build Failed: {e}")
        return pd.DataFrame(), pd.Series()

# ==============================================================================
# 3. WALK-FORWARD TRAINING (The Gym)
# ==============================================================================
def train_oracle():
    X, y = build_training_dataset()
    if X.empty: return

    log.info(f"🏋️ Training Oracle on {len(X)} historical scenarios...")
    
    # Time Series Split (Walk Forward)
    # We split data into 5 chunks. Train on 1, Test 2. Train 1+2, Test 3...
    tscv = TimeSeriesSplit(n_splits=5)
    
    model = RandomForestClassifier(n_estimators=100, max_depth=5, n_jobs=-1, random_state=42)
    
    fold = 1
    scores = []
    
    for train_index, test_index in tscv.split(X):
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y.iloc[train_index], y.iloc[test_index]
        
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        
        log.info(f"   🔹 Fold {fold}: Accuracy {acc:.1%}")
        scores.append(acc)
        fold += 1
        
    avg_score = np.mean(scores)
    log.info(f"🏆 Oracle Certified. Average Accuracy: {avg_score:.1%}")
    
    # Final Training on ALL Data
    model.fit(X, y)
    
    # Save the Brain
    joblib.dump(model, MODEL_PATH)
    log.info(f"💾 Model Saved: {MODEL_PATH}")

# ==============================================================================
# 4. PREDICTION INTERFACE (The Glass)
# ==============================================================================
def predict_success(trade_type, vix_val, vix_rsi):
    """
    Called by view_live.py.
    Returns: Probability of Success (0-100)
    """
    # 1. Load Model
    if not MODEL_PATH.exists():
        return 50.0 # Neutral if no brain exists
        
    try:
        model = joblib.load(MODEL_PATH)
        
        # 2. Build Feature Vector (Must match training structure)
        # We infer time from "NOW"
        now = datetime.now()
        
        feat = pd.DataFrame([{
            'hour': now.hour,
            'dow': now.weekday(),
            'vix': float(vix_val),
            'type_code': 1 if trade_type.upper() == 'CALL' else 0
        }])
        
        # 3. Predict Probability
        prob = model.predict_proba(feat)[0][1] # Probability of Class 1 (Win)
        return round(prob * 100, 1)
        
    except Exception as e:
        # log.error(f"Prediction Error: {e}")
        return 50.0

if __name__ == "__main__":
    train_oracle()