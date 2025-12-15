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
from sklearn.preprocessing import LabelEncoder

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OracleML")

MODEL_PATH = config.DATA_DIR / "oracle_v2.joblib"
TBL_SIGNALS = "signal_history_log"
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')

# TARGET CONFIGURATION
TARGET_WINDOW_MINS = 45     # Look ahead 45 minutes
SUCCESS_THRESHOLD = 0.0015  # 0.15% Move (~10-15% Option Contract Move)
TRUTH_TICKER = 'SPX'        # Using SPX as the dense data source

# ==============================================================================
# 2. DATASET CONSTRUCTION (The Memory)
# ==============================================================================
def build_training_dataset():
    """
    Joins Signals with Index Price Action (SPX) to determine theoretical success.
    Returns: X (Features), y (Target)
    """
    log.info(f"🧠 Constructing Training Dataset from Signal History vs {TRUTH_TICKER}...")
    
    if not config.DB_FILE.exists(): return None, None
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # A. FETCH SIGNALS
    try:
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if TBL_SIGNALS not in tables:
            log.warning(f"⚠️ {TBL_SIGNALS} not found. Run engine_scanner first.")
            con.close()
            return None, None

        df_sig = con.execute(f"SELECT * FROM {TBL_SIGNALS} ORDER BY timestamp_utc ASC").df()
        
        # B. FETCH MARKET DATA (SPX - The Liquid Truth)
        min_date = df_sig['timestamp_utc'].min() - timedelta(days=1)
        max_date = df_sig['timestamp_utc'].max() + timedelta(days=1)
        
        # Explicitly fetching SPX data
        df_mkt = con.execute(f"""
            SELECT datetime_utc, close 
            FROM {TBL_INDICES} 
            WHERE ticker = '{TRUTH_TICKER}' 
            AND datetime_utc >= '{min_date}' AND datetime_utc <= '{max_date}'
            ORDER BY datetime_utc ASC
        """).df()
        
        con.close()
    except Exception as e:
        log.error(f"Data Fetch Error: {e}")
        return None, None

    if df_sig.empty:
        log.warning("⚠️ No signals found in history.")
        return None, None
        
    if df_mkt.empty:
        log.warning(f"⚠️ No {TRUTH_TICKER} market data found to calculate outcomes.")
        return None, None

    # C. DETERMINE OUTCOMES (The "Oracle's Truth")
    df_mkt.sort_values('datetime_utc', inplace=True)
    df_sig.sort_values('timestamp_utc', inplace=True)
    
    # 1. Get Entry Price (Exact match or backward)
    df = pd.merge_asof(
        df_sig, 
        df_mkt.rename(columns={'close': 'entry_px'}),
        left_on='timestamp_utc', 
        right_on='datetime_utc', 
        direction='backward'
    )
    
    # 2. Get Exit Price (Entry Time + Window)
    df['exit_time_target'] = df['timestamp_utc'] + timedelta(minutes=TARGET_WINDOW_MINS)
    
    df = pd.merge_asof(
        df,
        df_mkt[['datetime_utc', 'close']].rename(columns={'close': 'exit_px', 'datetime_utc': 'actual_exit_time'}),
        left_on='exit_time_target',
        right_on='actual_exit_time',
        direction='backward',
        tolerance=timedelta(minutes=10) # Allow 10m data gap for SPX
    )
    
    # Drop signals where we don't have future data
    df.dropna(subset=['entry_px', 'exit_px'], inplace=True)
    
    # D. CALCULATE TARGET (Did it Win?)
    outcomes = []
    for idx, row in df.iterrows():
        is_call = 'LONG' in row['signal_type'] or 'BULL' in row['signal_type']
        
        change = (row['exit_px'] - row['entry_px']) / row['entry_px']
        
        if is_call:
            win = change > SUCCESS_THRESHOLD
        else:
            win = change < -SUCCESS_THRESHOLD
            
        outcomes.append(1 if win else 0)
        
    df['target'] = outcomes
    
    # E. FEATURE ENGINEERING
    regime_map = {'TRENDING': 1, 'CHOP': 0, 'UNKNOWN': 0}
    flow_map = {'BULL': 1, 'BEAR': -1, 'NEUTRAL': 0}
    
    df['regime_code'] = df['market_regime'].map(regime_map).fillna(0)
    df['flow_code'] = df['flow_bias'].map(flow_map).fillna(0)
    df['hour'] = df['timestamp_utc'].dt.hour
    df['dow'] = df['timestamp_utc'].dt.dayofweek
    df['is_call'] = np.where(df['signal_type'].str.contains('LONG'), 1, 0)
    
    # Ensure numeric types
    X = df[['vix_value', 'rsi_value', 'regime_code', 'flow_code', 'hour', 'dow', 'is_call']].copy()
    X = X.apply(pd.to_numeric)
    
    y = df['target']
    
    log.info(f"📚 Dataset Compiled: {len(X)} samples. Win Rate in Data: {y.mean():.1%}")
    return X, y

# ==============================================================================
# 3. MODEL TRAINING (The Education)
# ==============================================================================
def train_oracle():
    X, y = build_training_dataset()
    
    # Threshold for training
    if X is None or len(X) < 30:
        log.warning(f"⚠️ Not enough data to train Oracle (Found {len(X) if X is not None else 0}, Need 30).")
        return

    log.info("🏋️ Training Random Forest (Oracle v2)...")
    
    # TimeSeries Split Validation
    tscv = TimeSeriesSplit(n_splits=3)
    model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    
    scores = []
    fold = 1
    for train_index, test_index in tscv.split(X):
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y.iloc[train_index], y.iloc[test_index]
        
        if len(np.unique(y_train)) < 2: continue

        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        
        log.info(f"   Fold {fold}: Accuracy {acc:.2f}")
        scores.append(acc)
        fold += 1
        
    avg_score = np.mean(scores) if scores else 0.0
    log.info(f"🏆 Oracle Certified. Average Validation Accuracy: {avg_score:.1%}")
    
    # Final Training
    model.fit(X, y)
    
    joblib.dump(model, MODEL_PATH)
    log.info(f"💾 Model Saved: {MODEL_PATH}")

# ==============================================================================
# 4. PREDICTION INTERFACE (The Glass)
# ==============================================================================
def predict_success(signal_type, vix_val, rsi_val, market_regime, flow_bias):
    if not MODEL_PATH.exists(): return 50.0
        
    try:
        model = joblib.load(MODEL_PATH)
        now = datetime.now()
        
        regime_map = {'TRENDING': 1, 'CHOP': 0, 'UNKNOWN': 0}
        flow_map = {'BULL': 1, 'BEAR': -1, 'NEUTRAL': 0}
        
        feat = pd.DataFrame([{
            'vix_value': float(vix_val),
            'rsi_value': float(rsi_val),
            'regime_code': regime_map.get(market_regime, 0),
            'flow_code': flow_map.get(flow_bias, 0),
            'hour': now.hour,
            'dow': now.weekday(),
            'is_call': 1 if ('LONG' in signal_type or 'BULL' in signal_type) else 0
        }])
        
        probs = model.predict_proba(feat)
        success_prob = probs[0][1] * 100
        return success_prob
        
    except Exception as e:
        log.error(f"Prediction Error: {e}")
        return 50.0

if __name__ == "__main__":
    train_oracle()