import sys
import duckdb
import pandas as pd
from datetime import datetime
from pathlib import Path

# ==============================================================================
# SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("TrainingVault")

TBL_NAME = "optimal_training_manifest"

# ==============================================================================
# SCHEMA MANAGEMENT
# ==============================================================================
def init_vault():
    """Creates the Optimal Training Manifest table if it doesn't exist."""
    if not config.DB_FILE.exists():
        log.error("Database not found.")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # This table links PRICE ACTION (Gain) with MARKET STATE (Forensics)
        schema = f"""
            CREATE TABLE IF NOT EXISTS {TBL_NAME} (
                entry_time_utc TIMESTAMP PRIMARY KEY,
                exit_time_utc TIMESTAMP,
                trade_type VARCHAR,
                entry_price DOUBLE,
                exit_price DOUBLE,
                gain_points DOUBLE,
                
                -- Forensic Fingerprint (The AI Inputs)
                vix_rsi DOUBLE,
                vix_macd_hist DOUBLE,
                xsp_sigma DOUBLE,
                trend_slope DOUBLE,
                
                -- Metadata
                source VARCHAR, -- 'AUDITOR' or 'MANUAL'
                created_at TIMESTAMP
            )
        """
        con.execute(schema)
        con.close()
        log.info(f"✅ Training Vault ({TBL_NAME}) initialized.")
        
    except Exception as e:
        log.error(f"Vault Init Error: {e}")

# ==============================================================================
# I/O OPERATIONS
# ==============================================================================
def save_profile(trade_data, forensics, source="AUDITOR"):
    """
    Saves a 'Perfect Trade' profile to the vault.
    """
    init_vault() # Ensure table exists
    
    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # Construct the record
        record = {
            'entry_time_utc': trade_data['entry_ts'],
            'exit_time_utc': trade_data['exit_ts'],
            'trade_type': trade_data['type'],
            'entry_price': trade_data['entry_px'],
            'exit_price': trade_data['exit_px'],
            'gain_points': trade_data['points'],
            
            'vix_rsi': forensics.get('vix_rsi', 0),
            'vix_macd_hist': forensics.get('vix_macd_hist', 0),
            'xsp_sigma': forensics.get('linreg_deviation', 0),
            'trend_slope': forensics.get('trend_slope', 0),
            
            'source': source,
            'created_at': datetime.now()
        }
        
        # Convert to DataFrame for easy insertion
        df = pd.DataFrame([record])
        
        # Insert (OR IGNORE to prevent duplicates on re-runs)
        con.execute(f"INSERT OR IGNORE INTO {TBL_NAME} SELECT * FROM df")
        con.close()
        
        log.info(f"💾 Saved {source} Profile: {trade_data['type']} (+{trade_data['points']:.2f} pts)")
        return True
        
    except Exception as e:
        log.error(f"Save Profile Error: {e}")
        return False

def fetch_training_set():
    """
    Retrieves the Gold Standard dataset for the AI Oracle.
    """
    if not config.DB_FILE.exists(): return pd.DataFrame()
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        df = con.execute(f"SELECT * FROM {TBL_NAME} ORDER BY entry_time_utc DESC").df()
        con.close()
        return df
    except:
        return pd.DataFrame()

# ==============================================================================
# MANUAL TESTER
# ==============================================================================
if __name__ == "__main__":
    # Initialize the table
    init_vault()
    
    # Check what's inside
    df = fetch_training_set()
    if not df.empty:
        print("\n=== VAULT CONTENTS ===")
        print(df[['entry_time_utc', 'trade_type', 'gain_points', 'vix_rsi', 'source']].head())
        print(f"Total Profiles: {len(df)}")
    else:
        print("\n⚠️ Vault is empty. Run the Auditor + Snapshotter pipeline to fill it.")