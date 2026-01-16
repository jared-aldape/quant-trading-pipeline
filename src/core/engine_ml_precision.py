import sys
import duckdb
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OraclePrecision")

MODEL_PATH = config.DATA_DIR / "oracle_v3_precision.joblib"
TBL_SIM_LOG = getattr(config, 'TBL_SIM_LOG', 'active_simulation_log')
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')

# CONFIGURATION
MIN_PROFIT_THRESHOLD = 5.0  # Trade considered a "WIN" if PnL > $5

# ==============================================================================
# 2. DATASET CONSTRUCTION (The Optimal Profile)
# ==============================================================================
def build_precision_dataset():
    """
    Constructs dataset using 'Optimal Profile' (Backtest Logs) as Ground Truth.
    """
    log.info("💎 Constructing Dataset from OPTIMAL PROFILE (Backtest Logs)...")
    
    if not config.DB_FILE.exists(): return None
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Fetch Training Candidates (Completed Simulations)
        # We join the SIM LOG with the MARKET CONTEXT at that time
        query = f"""
            SELECT 
                s.entry_time,
                s.ticker,
                s.net_pnl,
                s.meta_data,
                i.close as entry_price,
                v.close as vix_val
            FROM {TBL_SIM_LOG} s
            LEFT JOIN {TBL_INDICES} i ON s.entry_time = i.datetime_utc AND i.ticker = 'XSP'
            LEFT JOIN {TBL_INDICES} v ON s.entry_time = v.datetime_utc AND v.ticker = 'VIX'
            WHERE s.status = 'CLOSED'
            AND s.entry_time IS NOT NULL
        """
        df = con.execute(query).df()
        con.close()

        if df.empty:
            log.warning("⚠️ No simulation history found for training.")
            return None

        # 2. Feature Engineering
        X = []
        y = []

        for _, row in df.iterrows():
            # Target: Did we make money?
            label = 1 if row['net_pnl'] > MIN_PROFIT_THRESHOLD else 0
            
            # Features: Parse metadata if available, otherwise use raw
            # We try to extract 'RSI' or signal type from metadata JSON
            try:
                meta = str(row['meta_data'])
                is_call = 1 if 'CALL' in meta.upper() or 'LONG' in meta.upper() else 0
                # Default RSI to 50 if missing (neutral)
                rsi = 50.0 
                if 'rsi' in meta.lower():
                    # diverse parsing logic could go here
                    pass
            except:
                is_call = 0
                rsi = 50.0

            # SIMPLE FEATURE SET: [Is_Call, VIX, RSI]
            # (In v4.1 we can expand this to include slope/momentum)
            vix = row['vix_val'] if pd.notnull(row['vix_val']) else 15.0
            
            X.append([is_call, vix, rsi])
            y.append(label)

        return pd.DataFrame(X, columns=['is_call', 'vix', 'rsi']), pd.Series(y)

    except Exception as e:
        log.error(f"Dataset Build Error: {e}")
        return None

# ==============================================================================
# 3. TRAINING ENGINE
# ==============================================================================
def train_precision_oracle():
    """
    Retrains the model using the latest simulation outcomes.
    """
    data = build_precision_dataset()
    if not data: return

    X, y = data
    
    # 🛡️ SAFETY: MINIMUM DATA REQUIREMENT
    if len(X) < 10:
        log.warning(f"⚠️ Insufficient data to train ({len(X)} samples). Need 10+.")
        return

    # 🛡️ SAFETY: CLASS DIVERSITY CHECK
    unique_classes = np.unique(y)
    if len(unique_classes) < 2:
        log.warning(f"⚠️ Training Aborted: Data only contains class {unique_classes[0]}. Needs Wins AND Losses.")
        return

    # Train
    tscv = TimeSeriesSplit(n_splits=3)
    model = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42)
    
    scores = []
    try:
        for train_index, test_index in tscv.split(X):
            X_train, X_test = X.iloc[train_index], X.iloc[test_index]
            y_train, y_test = y.iloc[train_index], y.iloc[test_index]
            
            # Skip split if only one class present in training fold
            if len(np.unique(y_train)) < 2: continue
            
            model.fit(X_train, y_train)
            acc = accuracy_score(y_test, model.predict(X_test))
            scores.append(acc)
    except Exception as e:
        log.warning(f"CV Loop Error: {e}")

    avg = np.mean(scores) if scores else 0.0
    
    # Final Fit on All Data
    model.fit(X, y)
    
    joblib.dump(model, MODEL_PATH)
    log.info(f"🏆 ORACLE V4 TRAINED. Validation Accuracy: {avg:.1%}")

# ==============================================================================
# 4. INFERENCE (The Guard)
# ==============================================================================
def predict_success(signal_type, vix_val, rsi_val):
    """
    Returns probability of success (0-100).
    Now robust against 'Single Class' model errors.
    """
    if not MODEL_PATH.exists(): return 50.0
    
    try:
        model = joblib.load(MODEL_PATH)
        
        # Parse Input
        s_type = str(signal_type).upper()
        is_call = 1 if ('LONG' in s_type or 'BULL' in s_type or 'CALL' in s_type) else 0
        
        # Construct Vector
        X_new = pd.DataFrame([[is_call, vix_val, rsi_val]], columns=['is_call', 'vix', 'rsi'])
        
        # 🛡️ ROBUST PREDICTION
        try:
            probs = model.predict_proba(X_new)
            
            # Case A: Model knows both classes (Normal)
            if probs.shape[1] == 2:
                return probs[0][1] * 100.0
            
            # Case B: Model only knows ONE class (Brain Damaged)
            else:
                # If the only class it knows is 1 (Win), return 100%
                # If the only class it knows is 0 (Loss), return 0%
                single_class = model.classes_[0]
                return 100.0 if single_class == 1 else 0.0
                
        except Exception as pred_e:
            # Fallback for weird sklearn edge cases
            return 50.0

    except Exception as e:
        # log.error(f"Prediction Error: {e}") # Silenced to prevent spam
        return 50.0