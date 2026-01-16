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
# Flexible table names to prevent "Table Not Found" errors
TBL_SIM_LOG = getattr(config, 'TBL_SIM_LOG', 'active_simulation_log')
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')
TBL_TRAINING = "optimal_training_manifest"

# CONFIGURATION
MIN_PROFIT_THRESHOLD = 5.0  # Trade considered a "WIN" if PnL > $5

# ==============================================================================
# 2. DATASET CONSTRUCTION (The Optimal Profile)
# ==============================================================================
def build_precision_dataset():
    """
    Constructs dataset using 'Optimal Profile' (Manual/Validated Trades) as Ground Truth.
    Includes NEW FEATURES: Market Regime & Flow Bias.
    """
    log.info("💎 Constructing Dataset from OPTIMAL PROFILE...")
    
    if not config.DB_FILE.exists(): return None
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # Check if we have the advanced training manifest
    tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
    target_table = TBL_TRAINING if TBL_TRAINING in tables else TBL_SIM_LOG
    
    if target_table not in tables:
        log.warning("⚠️ No training data found.")
        con.close()
        return None

    # Fetch validated trades
    # We try to pull extra metadata if available
    try:
        if target_table == TBL_TRAINING:
            # New Schema
            query = f"""
                SELECT trade_type, entry_time_utc, gain_points, vix_rsi, xsp_sigma, trend_slope 
                FROM {target_table}
            """
        else:
            # Legacy Schema
            query = f"""
                SELECT ticker as trade_type, entry_time as entry_time_utc, net_pnl as gain_points
                FROM {target_table}
            """
        
        df = con.execute(query).df()
        con.close()
        
        if df.empty: return None

        # Feature Engineering
        df['target'] = (df['gain_points'] > 0).astype(int)
        
        # Parse 'CALL'/'PUT'
        df['is_call'] = df['trade_type'].astype(str).str.upper().apply(lambda x: 1 if 'CALL' in x or 'LONG' in x else 0)
        
        # Extract Time Features
        df['entry_time_utc'] = pd.to_datetime(df['entry_time_utc'])
        df['hour'] = df['entry_time_utc'].dt.hour
        df['dow'] = df['entry_time_utc'].dt.dayofweek
        
        # If missing VIX columns (Legacy), fill defaults
        if 'vix_rsi' not in df.columns: df['vix_rsi'] = 50.0
        if 'xsp_sigma' not in df.columns: df['xsp_sigma'] = 0.0
        if 'trend_slope' not in df.columns: df['trend_slope'] = 0.0
        
        # New Features (Placeholders for now, populated by proper join in future)
        df['regime_code'] = 0 # Unknown
        df['flow_code'] = 0   # Neutral
        
        features = ['vix_rsi', 'xsp_sigma', 'trend_slope', 'hour', 'dow', 'is_call', 'regime_code', 'flow_code']
        return df[features], df['target']

    except Exception as e:
        log.error(f"Dataset Build Error: {e}")
        return None

# ==============================================================================
# 3. TRAINING ENGINE
# ==============================================================================
def train_precision_oracle():
    """
    Retrains the model using the latest labeled data.
    """
    data = build_precision_dataset()
    if not data: return
    
    X, y = data
    if len(X) < 10:
        log.warning("⚠️ Insufficient data for training (<10 samples).")
        return

    # Time-Series Cross-Validation
    tscv = TimeSeriesSplit(n_splits=3)
    model = RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42)
    
    scores = []
    try:
        for train_index, test_index in tscv.split(X):
            X_train, X_test = X.iloc[train_index], X.iloc[test_index]
            y_train, y_test = y.iloc[train_index], y.iloc[test_index]
            
            if len(np.unique(y_train)) < 2: continue # Skip if only one class
            
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            scores.append(accuracy_score(y_test, pred))
            
        avg = np.mean(scores) if scores else 0
        log.info(f"🏆 ORACLE V4 TRAINED. Val Accuracy: {avg:.1%}")
        
        # Final Fit
        model.fit(X, y)
        joblib.dump(model, MODEL_PATH)
        log.info(f"💾 Model Saved: {MODEL_PATH}")
        
    except Exception as e:
        log.error(f"Training Failed: {e}")

# ==============================================================================
# 4. PREDICTION INTERFACE (BACKWARD COMPATIBLE)
# ==============================================================================
def predict_success(signal_type, vix_val, rsi_val, market_regime="UNKNOWN", flow_bias="NEUTRAL"):
    """
    Returns: Probability of Success (0-100)
    Accepts new context arguments but handles legacy models gracefully.
    """
    if not MODEL_PATH.exists(): return 50.0
        
    try:
        model = joblib.load(MODEL_PATH)
        now = datetime.now()
        
        # Encode Inputs
        is_call = 1 if ('LONG' in str(signal_type).upper() or 'CALL' in str(signal_type).upper()) else 0
        
        regime_map = {'TRENDING': 1, 'CHOP': 0, 'CRITICAL_SQUEEZE': 2}
        flow_map = {'BULL': 1, 'BEAR': -1, 'NEUTRAL': 0}
        
        regime_code = regime_map.get(market_regime, 0)
        flow_code = flow_map.get(flow_bias, 0)
        
        # 1. ATTEMPT V4 FEATURE SET (Enhanced)
        feat_v4 = pd.DataFrame([{
            'vix_rsi': float(rsi_val),
            'xsp_sigma': float(vix_val) / 100.0, # Proxy
            'trend_slope': 0.0, # Proxy
            'hour': now.hour,
            'dow': now.weekday(),
            'is_call': is_call,
            'regime_code': regime_code,
            'flow_code': flow_code
        }])
        
        try:
            # Try predicting with full feature set
            prob = model.predict_proba(feat_v4)[0][1]
            return prob * 100
        except ValueError:
            # ⚡ FALLBACK: Model expects old features (V3)
            # Remove new columns to match legacy model shape
            # Assuming old model used: vix_value, rsi_value, regime_code, flow_code, hour, dow, is_call
            # Or simplified set. We try the most common legacy set.
            
            # Common V3 Legacy Set: vix_value, rsi_value, hour, dow, is_call
            feat_v3 = pd.DataFrame([{
                'vix_value': float(vix_val),
                'rsi_value': float(rsi_val),
                'hour': now.hour,
                'dow': now.weekday(),
                'is_call': is_call
            }])
            
            try:
                prob = model.predict_proba(feat_v3)[0][1]
                return prob * 100
            except:
                # If all else fails, return neutral
                return 50.0

    except Exception as e:
        log.error(f"Prediction Error: {e}")
        return 50.0