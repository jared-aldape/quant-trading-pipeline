import sys
import duckdb
import pandas as pd
import numpy as np
import joblib
import pandas_ta as ta
from pathlib import Path
from datetime import datetime
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

# TARGET THE V5 MODEL
MODEL_PATH = config.DATA_DIR / "oracle_v5_precision.joblib"
TBL_SIM_LOG = getattr(config, 'TBL_SIM_LOG', 'active_simulation_log')
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')

# ==============================================================================
# 2. FEATURE ENGINEERING (The Alpha Miner)
# ==============================================================================
def calculate_cross(macd, signal):
    """Calculates Golden/Death Crosses: 1 for Bull Cross, -1 for Bear Cross, 0 for None"""
    diff = macd - signal
    # Cross happens when sign changes
    cross = np.where((diff > 0) & (diff.shift(1) <= 0), 1, 0) # Bull
    cross = np.where((diff < 0) & (diff.shift(1) >= 0), -1, cross) # Bear
    return cross

def build_precision_dataset():
    """
    Constructs the feature matrix based on the +30% ATM+1 parameters.
    """
    print("\n" + "="*80)
    log.info("💎 INITIATING ALPHA MINING (Target: 30%+ ROI)...")
    
    if not config.DB_FILE.exists(): 
        log.error("❌ Database not found.")
        return None
        
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. Fetch Market Context
    query_idx = f"SELECT datetime_utc, ticker, close, high, low FROM {TBL_INDICES} ORDER BY datetime_utc ASC"
    try:
        df_mkt = con.execute(query_idx).df()
    except Exception as e:
        log.error(f"Could not load indices: {e}")
        con.close()
        return None
    
    # 2. Fetch True-Win Trades (Ground Truth)
    # The backtester logged TRUE WINS when status='WIN' and reason='TARGET_30_PCT'
    query_trades = f"SELECT * FROM {TBL_SIM_LOG} WHERE source_id = 'BACKTEST'"
    try:
        df_trades = con.execute(query_trades).df()
    except Exception as e:
        log.warning(f"⚠️ No trades found in simulation log: {e}")
        con.close()
        return None
        
    con.close()

    if df_trades.empty:
        log.warning("⚠️ No trades found in simulation log. Cannot train.")
        return None

    log.info("   ⚙️ Engineering Contextual Variables (MACD, RSI, ADX, Crosses)...")
    # --- TECHNICAL CALCULATION (Procedural Data Extraction) ---
    vix = df_mkt[df_mkt['ticker'] == 'VIX'].copy()
    vix_macd = ta.macd(vix['close'])
    if vix_macd is not None and not vix_macd.empty:
        vix['macd'] = vix_macd['MACD_12_26_9']
        vix['signal'] = vix_macd['MACDs_12_26_9']
        vix['hist'] = vix_macd['MACDh_12_26_9']
        vix['cross'] = calculate_cross(vix['macd'], vix['signal'])
    else:
        vix['hist'] = 0; vix['cross'] = 0
    vix['rsi'] = ta.rsi(vix['close'])

    xsp = df_mkt[df_mkt['ticker'] == 'XSP'].copy()
    xsp_macd = ta.macd(xsp['close'])
    if xsp_macd is not None and not xsp_macd.empty:
        xsp['macd'] = xsp_macd['MACD_12_26_9']
        xsp['signal'] = xsp_macd['MACDs_12_26_9']
        xsp['hist'] = xsp_macd['MACDh_12_26_9']
        xsp['cross'] = calculate_cross(xsp['macd'], xsp['signal'])
    else:
        xsp['hist'] = 0; xsp['cross'] = 0
        
    adx_df = ta.adx(xsp['high'], xsp['low'], xsp['close'])
    if adx_df is not None and not adx_df.empty:
        xsp['adx'] = adx_df['ADX_14']
    else:
        xsp['adx'] = 20

    # --- FEATURE MERGE ---
    X, y = [], []
    wins, losses = 0, 0
    
    # Sort for merge_asof logic
    vix = vix.dropna().sort_values('datetime_utc')
    xsp = xsp.dropna().sort_values('datetime_utc')

    # ⚡ FIX: Force 'vix' and 'xsp' indexes to be timezone-naive to match DuckDB outputs
    vix['datetime_utc'] = pd.to_datetime(vix['datetime_utc']).dt.tz_localize(None)
    xsp['datetime_utc'] = pd.to_datetime(xsp['datetime_utc']).dt.tz_localize(None)

    for _, trade in df_trades.iterrows():
        # ⚡ FIX: Force trade time to be naive as well. Apples to Apples.
        t_time = pd.to_datetime(trade['entry_time']).tz_localize(None)
            
        v_match = vix[vix['datetime_utc'] <= t_time].tail(1)
        x_match = xsp[xsp['datetime_utc'] <= t_time].tail(1)
        
        if v_match.empty or x_match.empty: continue
            
        v_ctx = v_match.iloc[0]
        x_ctx = x_match.iloc[0]
        
        # 🎯 TARGET: Did it hit the 30% ROI?
        # ⚡ FIX: Added backward compatibility so it instantly recognizes your previous 671 trades
        is_win = 1 if trade['status'] == 'WIN' or trade['reason'] == 'TARGET_30_PCT' else 0
        
        if is_win: wins += 1
        else: losses += 1
            
        y.append(is_win)
        
        # FEATURE VECTOR: The Overlap Hunt
        is_call = 1 if 'C' in str(trade['ticker']).upper() else 0
        hour = t_time.hour
        
        X.append([
            is_call,
            v_ctx['hist'],    # VIX Expansion / Contraction
            v_ctx['cross'],   # VIX MACD Cross (-1 = Death, 1 = Golden)
            v_ctx['rsi'],     # VIX Overbought/Oversold
            x_ctx['hist'],    # XSP Momentum
            x_ctx['cross'],   # XSP MACD Cross
            x_ctx['adx'],     # Trend Strength (Are we in the chop?)
            hour              # Time of Day Cluster
        ])

    feature_names = [
        'Call/Put Bias', 'VIX MACD Hist', 'VIX MACD Cross', 'VIX RSI',
        'XSP MACD Hist', 'XSP MACD Cross', 'XSP ADX', 'Hour of Day'
    ]
    
    df_X = pd.DataFrame(X, columns=feature_names)
    df_y = pd.Series(y)

    log.info(f"   📊 ALPHA HARVEST: 30%+ True Wins: {wins} | Losses/Chop: {losses}")
    
    if wins == 0 or losses == 0:
        log.warning("   ⚠️ SEVERE IMBALANCE: Cannot train. Model needs both examples.")

    return df_X, df_y

# ==============================================================================
# 3. TRAINING & DEPLOYMENT
# ==============================================================================
def train_precision_oracle():
    data = build_precision_dataset()
    if not data: return
    X, y = data
    
    log.info("\n🧠 INITIATING ORACLE NEURAL TRAINING...")
    log.info(f"   📐 Feature Vector Length: {len(X.columns)}")

    if len(X) < 10:
        log.warning(f"⚠️ Insufficient data ({len(X)} samples).")
        return

    # 🛡️ Institutional Guard: 'balanced' forces the model to weigh class proportions
    model = RandomForestClassifier(
        n_estimators=200, 
        max_depth=6, 
        class_weight='balanced', 
        random_state=42
    )
    
    # Quick Fold Test
    tscv = TimeSeriesSplit(n_splits=3)
    scores = []
    for train_index, test_index in tscv.split(X):
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y.iloc[train_index], y.iloc[test_index]
        if len(np.unique(y_train)) > 1:
            model.fit(X_train, y_train)
            scores.append(accuracy_score(y_test, model.predict(X_test)))
            
    avg_score = np.mean(scores) if scores else 0.0
    
    # Final Fit
    model.fit(X, y)
    joblib.dump(model, MODEL_PATH)
    
    log.info(f"🏆 ORACLE V5 DEPLOYED. Cross-Validation: {avg_score:.1%}")
    print("="*80 + "\n")

def predict_success(signal_type, vix_val=15.0, rsi_val=50.0, trade_hour=None, **kwargs):
    """
    Prediction endpoint for LIVE inference. 
    (Backwards compatible with backtester calls)
    """
    if not MODEL_PATH.exists(): return 50.0
    try:
        model = joblib.load(MODEL_PATH)
        is_call = 1 if ('LONG' in str(signal_type).upper() or 'BULL' in str(signal_type).upper() or 'CALL' in str(signal_type).upper()) else 0
        hour = trade_hour if trade_hour is not None else datetime.now().hour
        
        # During live inference, these should be dynamically passed.
        # Fallbacks to 0 for crosses if not explicitly provided during legacy backtest loop
        v_hist = kwargs.get('vix_hist', 0)
        v_cross = kwargs.get('vix_cross', 0)
        x_hist = kwargs.get('xsp_hist', 0)
        x_cross = kwargs.get('xsp_cross', 0)
        adx = kwargs.get('adx', 20)
        
        # Must match feature_names order
        X_new = pd.DataFrame([[
            is_call, v_hist, v_cross, rsi_val, x_hist, x_cross, adx, hour
        ]], columns=[
            'Call/Put Bias', 'VIX MACD Hist', 'VIX MACD Cross', 'VIX RSI',
            'XSP MACD Hist', 'XSP MACD Cross', 'XSP ADX', 'Hour of Day'
        ])
        
        probs = model.predict_proba(X_new)
        if probs.shape[1] == 2: return probs[0][1] * 100.0
        else: return 100.0 if model.classes_[0] == 1 else 0.0
    except Exception as e:
        log.error(f"Prediction Error: {e}")
        return 0.0

if __name__ == "__main__":
    train_precision_oracle()