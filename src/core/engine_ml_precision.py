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
TBL_SIGNALS = "option_signal_manifest"
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')
TBL_OPTIONS = getattr(config, 'TBL_OPTIONS', 'options_1m')

# TARGET CONFIGURATION
TARGET_WINDOW_MINS = 45     
MIN_OPTION_ROI = 0.10       # Require 10% ROI on the OPTION (Real Profit)

# ==============================================================================
# 2. HELPER: OPRA TICKER CONSTRUCTION
# ==============================================================================
def find_best_contract(con, signal_time, signal_type, underlying_price):
    """
    Finds the closest 0DTE ATM Option for the given signal.
    """
    # 1. Determine Target Expiration (Same Day = 0DTE)
    trade_date = signal_time.date()
    
    # 2. Determine Target Strike
    # XSP is 1/10th of SPX usually. Our signals track XSP.
    if underlying_price > 2000:
        target_strike = underlying_price / 10.0
    else:
        target_strike = underlying_price
        
    target_strike = round(target_strike)
    
    # 3. Determine Type
    is_call = 'LONG' in signal_type or 'BULL' in signal_type
    opt_type = 'C' if is_call else 'P'
    
    # 4. Query DB for available contracts on this day/expiry
    try:
        start_search = signal_time.strftime('%Y-%m-%d %H:%M:%S')
        end_search = (signal_time + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
        
        q = f"""
            SELECT ticker, strike, abs(strike - {target_strike}) as dist
            FROM {TBL_OPTIONS}
            WHERE datetime_utc >= '{start_search}' 
            AND datetime_utc <= '{end_search}'
            AND expiration = '{trade_date}'
            AND type = '{opt_type}'
            ORDER BY dist ASC, datetime_utc ASC
            LIMIT 1
        """
        result = con.execute(q).fetchone()
        
        if result:
            return result[0] # Return Ticker
    except Exception:
        return None
        
    return None

# ==============================================================================
# 3. DATASET CONSTRUCTION (The Reality Check)
# ==============================================================================
def build_precision_dataset():
    log.info("💎 Constructing PRECISION Training Dataset (Options Reality)...")
    
    if not config.DB_FILE.exists(): return None, None
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # A. FETCH SIGNALS
    try:
        df_sig = con.execute(f"SELECT * FROM {TBL_SIGNALS} ORDER BY timestamp_utc ASC").df()
    except:
        return None, None
        
    if df_sig.empty: return None, None

    # B. FETCH INDEX PRICES (To find ATM Strike)
    min_date = df_sig['timestamp_utc'].min()
    max_date = df_sig['timestamp_utc'].max() + timedelta(days=1)
    
    df_idx = con.execute(f"""
        SELECT datetime_utc, close 
        FROM {TBL_INDICES} 
        WHERE ticker = 'SPX' 
        AND datetime_utc >= '{min_date}' AND datetime_utc <= '{max_date}'
        ORDER BY datetime_utc
    """).df()
    
    if df_idx.empty:
        con.close()
        return None, None

    # Merge Index Price to Signals
    df_idx.sort_values('datetime_utc', inplace=True)
    df_sig.sort_values('timestamp_utc', inplace=True)
    
    df = pd.merge_asof(
        df_sig,
        df_idx.rename(columns={'close': 'underlying_px'}),
        left_on='timestamp_utc',
        right_on='datetime_utc',
        direction='backward'
    )
    df.dropna(subset=['underlying_px'], inplace=True)

    # C. ITERATE AND SIMULATE OPTION TRADES
    valid_samples = []
    log.info(f"   Simulating Options Trades for {len(df)} signals...")
    
    for idx, row in df.iterrows():
        # 1. Find Contract
        ticker = find_best_contract(con, row['timestamp_utc'], row['signal_type'], row['underlying_px'])
        if not ticker: continue
            
        # 2. Get Entry Price
        entry_time_str = row['timestamp_utc'].strftime('%Y-%m-%d %H:%M:%S')
        q_entry = f"SELECT close FROM {TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= '{entry_time_str}' ORDER BY datetime_utc ASC LIMIT 1"
        entry_px_res = con.execute(q_entry).fetchone()
        if not entry_px_res: continue
        entry_px = entry_px_res[0]
        
        # 3. Get Exit Price
        exit_time = row['timestamp_utc'] + timedelta(minutes=TARGET_WINDOW_MINS)
        exit_time_str = exit_time.strftime('%Y-%m-%d %H:%M:%S')
        q_exit = f"SELECT close FROM {TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= '{exit_time_str}' ORDER BY datetime_utc ASC LIMIT 1"
        exit_px_res = con.execute(q_exit).fetchone()
        if not exit_px_res: continue
        exit_px = exit_px_res[0]
        
        # 4. Calculate ROI
        roi = (exit_px - entry_px) / entry_px
        
        # 5. Build Feature Row
        regime_map = {'TRENDING': 1, 'CHOP': 0, 'UNKNOWN': 0}
        flow_map = {'BULL': 1, 'BEAR': -1, 'NEUTRAL': 0}
        
        valid_samples.append({
            'vix_value': float(row['vix_value']),
            'rsi_value': float(row['rsi_value']),
            'regime_code': regime_map.get(row['market_regime'], 0),
            'flow_code': flow_map.get(row['flow_bias'], 0),
            'hour': row['timestamp_utc'].hour,
            'dow': row['timestamp_utc'].weekday(),
            'is_call': 1 if ('LONG' in row['signal_type'] or 'BULL' in row['signal_type']) else 0,
            'target': 1 if roi > MIN_OPTION_ROI else 0
        })

    con.close()
    
    if not valid_samples: return None, None
        
    df_train = pd.DataFrame(valid_samples)
    X = df_train[['vix_value', 'rsi_value', 'regime_code', 'flow_code', 'hour', 'dow', 'is_call']]
    y = df_train['target']
    
    log.info(f"💎 Precision Dataset: {len(X)} matches. Win Rate (Real Options): {y.mean():.1%}")
    return X, y

# ==============================================================================
# 4. TRAINING EXECUTION
# ==============================================================================
def train_precision_oracle():
    X, y = build_precision_dataset()
    
    if X is None or len(X) < 20:
        log.warning("⚠️ Insufficient Options Data overlap.")
        return

    log.info("🚀 Training Precision Oracle (v3)...")
    
    tscv = TimeSeriesSplit(n_splits=3)
    model = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42)
    
    scores = []
    for train_index, test_index in tscv.split(X):
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y.iloc[train_index], y.iloc[test_index]
        if len(np.unique(y_train)) < 2: continue
        model.fit(X_train, y_train)
        acc = accuracy_score(y_test, model.predict(X_test))
        scores.append(acc)
        
    avg = np.mean(scores) if scores else 0
    log.info(f"🏆 PRECISION MODEL TRAINED. Validation Accuracy: {avg:.1%}")
    
    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)
    log.info(f"💾 Model Saved: {MODEL_PATH}")

# ==============================================================================
# 5. PREDICTION INTERFACE (THE MISSING LINK)
# ==============================================================================
def predict_success(signal_type, vix_val, rsi_val, market_regime, flow_bias):
    """
    Returns: Probability of Success (0-100)
    """
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
    train_precision_oracle()