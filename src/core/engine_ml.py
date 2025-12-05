import sys
import duckdb
import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import strat_fractal

log = get_logger("Oracle_ML")
MODEL_PATH = config.DATA_DIR / "model_fractal.pkl"

# ==============================================================================
# 2. DATA ENRICHMENT (The Context)
# ==============================================================================
def fetch_training_data():
    """
    Joins Simulation Logs with Market Context (VIX, RSI) to create a dataset.
    """
    if not config.DB_FILE.exists(): return pd.DataFrame()
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # A. Fetch Trades (Target)
    try:
        trades = con.execute(f"""
            SELECT entry_time, type, pnl, return_pct 
            FROM {config.TBL_SIM_LOG} 
            WHERE pnl IS NOT NULL
        """).df()
    except:
        return pd.DataFrame()
        
    if trades.empty: return pd.DataFrame()

    # B. Fetch VIX History (Features)
    vix = con.execute(f"SELECT datetime_utc, close FROM {config.TBL_INDICES} WHERE ticker='VIX' ORDER BY datetime_utc ASC").df()
    con.close()
    
    if vix.empty: return pd.DataFrame()

    # CRITICAL FIX: Standardize VIX to UTC Aware
    vix['datetime_utc'] = pd.to_datetime(vix['datetime_utc'])
    if vix['datetime_utc'].dt.tz is None:
        vix['datetime_utc'] = vix['datetime_utc'].dt.tz_localize('UTC')
    else:
        vix['datetime_utc'] = vix['datetime_utc'].dt.tz_convert('UTC')
        
    vix.set_index('datetime_utc', inplace=True)
    vix = strat_fractal.calculate_rsi(vix)
    
    # C. Feature Engineering
    features = []
    
    # CRITICAL FIX: Standardize Trades to UTC Aware
    trades['entry_time'] = pd.to_datetime(trades['entry_time'])
    if trades['entry_time'].dt.tz is None:
        # DB stores Local Time (PST) -> Convert to Aware UTC
        trades['entry_time'] = trades['entry_time'].dt.tz_localize(config.TZ_LOCAL).dt.tz_convert('UTC')
    else:
        trades['entry_time'] = trades['entry_time'].dt.tz_convert('UTC')
    
    for i, row in trades.iterrows():
        ts = row['entry_time']
        
        try:
            # 1. Time Features
            hour = ts.astimezone(config.TZ_LOCAL).hour
            
            # 2. Market Features (Lookup VIX at that time)
            # method='pad' gets the last known VIX value before the trade
            idx = vix.index.get_indexer([ts], method='pad')[0]
            
            if idx == -1: continue # No VIX data prior to trade
            
            vix_row = vix.iloc[idx]
            vix_val = vix_row['close']
            vix_rsi = vix_row['rsi']
            
            # Check for NaN (e.g. start of RSI calc)
            if pd.isna(vix_rsi): continue

            # Target: 1 if Win, 0 if Loss
            target = 1 if row['pnl'] > 0 else 0
            
            features.append({
                'hour': hour,
                'vix_level': vix_val,
                'vix_rsi': vix_rsi,
                'trade_type': 1 if row['type'].lower() == 'call' else 0, # Encode Type
                'target': target
            })
        except Exception as e:
            # log.warning(f"Row skipped: {e}")
            continue
            
    return pd.DataFrame(features)

# ==============================================================================
# 3. BRAIN TRAINING
# ==============================================================================
def train_model():
    log.info("🧠 Waking up the Oracle...")
    
    df = fetch_training_data()
    
    # TACTICAL OVERRIDE: Low threshold for boot-up
    if df.empty or len(df) < 5:
        log.warning(f"⚠️ Insufficient Matched Data ({len(df)} trades). Check VIX/Trade alignment.")
        return
        
    log.info(f"📚 Training on {len(df)} forensic samples...")

    # X = Features, y = Target
    feature_cols = ['hour', 'vix_level', 'vix_rsi', 'trade_type']
    X = df[feature_cols]
    y = df['target']
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Initialize Random Forest
    clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    clf.fit(X_train, y_train)
    
    # Evaluate
    if len(X_test) > 0:
        preds = clf.predict(X_test)
        acc = accuracy_score(y_test, preds)
        prec = precision_score(y_test, preds, zero_division=0)
        log.info(f"🎓 Training Complete. Accuracy: {acc:.2f} | Precision: {prec:.2f}")
    else:
        log.info("🎓 Training Complete (Training set only).")
    
    # Save
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(clf, f)
    log.info(f"💾 Brain saved to {MODEL_PATH}")

# ==============================================================================
# 4. INFERENCE (PREDICTION)
# ==============================================================================
def predict_success(trade_type, current_vix, current_rsi):
    """
    Returns a probability (0-100%) for a proposed trade.
    """
    if not MODEL_PATH.exists(): return 50.0 
    
    try:
        with open(MODEL_PATH, 'rb') as f:
            clf = pickle.load(f)
            
        hour = datetime.now(config.TZ_LOCAL).hour
        type_code = 1 if trade_type.lower() == 'call' else 0
        
        # Create Feature Vector
        X_new = pd.DataFrame([[hour, current_vix, current_rsi, type_code]], 
                             columns=['hour', 'vix_level', 'vix_rsi', 'trade_type'])
        
        # Get Probability of Class 1 (Win)
        prob = clf.predict_proba(X_new)[0][1]
        return round(prob * 100, 1)
        
    except Exception as e:
        log.error(f"Prediction Failed: {e}")
        return 50.0

# 5. LIVE SESSION INGESTION (FEEDBACK LOOP)
def ingest_live_session():
    """
    Harvests 'Real Combat' data from live_session.json and commits to TBL_SIM_LOG
    so the AI can learn from it.
    """
    session_path = config.DATA_DIR / "live_session.json"
    if not session_path.exists(): return
    
    try:
        with open(session_path, 'r') as f:
            data = json.load(f)
            
        trades = data.get('trades', [])
        if not trades: return
        
        con = duckdb.connect(str(config.DB_FILE))
        
        db_rows = []
        for t in trades:
            if t.get('pnl') is None: continue
            
            # Map Live Trade dict to DB Schema
            # Ensure types match TBL_SIM_LOG structure
            entry = {
                'run_id': 'LIVE_EXECUTION',
                'strategy_mode': 'MANUAL_OVERRIDE',
                'timestamp': datetime.now(),
                'entry_time': pd.to_datetime(t['entry_time']),
                'exit_time': pd.to_datetime(t['exit_time']),
                'ticker': t['ticker'],
                'type': t['type'],
                'signal_rank': 1, # Default
                'duration_str': 'N/A',
                'duration_mins': 0.0, # Could calc
                'reason': t.get('reason', 'MANUAL'),
                'entry_px': t['entry_px'],
                'exit_px': t['exit_px'],
                'return_pct': (t['pnl'] / (t['entry_px'] * 100 * t['contracts'])) * 100 if t['entry_px'] > 0 else 0,
                'pnl': t['pnl'],
                'position_size': t['entry_px'] * 100 * t['contracts'],
                'start_balance': 0.0, # Not tracking full portfolio here
                'end_balance': 0.0,
                'balance': 0.0
            }
            db_rows.append(entry)
            
        # Bulk Insert (using DataFrame is safer for type handling)
        if db_rows:
            df = pd.DataFrame(db_rows)
            con.execute(f"INSERT INTO {config.TBL_SIM_LOG} SELECT * FROM df")
            log.info(f"📥 Ingested {len(df)} live trades into the Brain.")
            
        con.close()
        
        # TRIGGER RETRAIN
        train_model()
        
    except Exception as e:
        log.error(f"Live Ingest Failed: {e}")

if __name__ == "__main__":
    train_model()