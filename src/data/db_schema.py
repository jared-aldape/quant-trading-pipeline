import sys
import os
import duckdb
import shutil
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V3.3: PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SchemaManager")

# ==============================================================================
# 2. FAILSAFE TABLE DEFINITIONS
# ==============================================================================
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')
TBL_RISK_FREE = getattr(config, 'TBL_RISK_FREE', 'risk_free_rate_daily')
TBL_MACRO_FLOW = getattr(config, 'TBL_MACRO_FLOW', 'macro_flow_state')
TBL_SIM_LOG = getattr(config, 'TBL_SIM_LOG', 'active_simulation_log')
TBL_RH_LEDGER = "active_rh_log"
TBL_SIGNAL_LOG = "signal_history_log"  # <--- NEW: Forensics Table

# ==============================================================================
# 3. SAFETY PROTOCOLS
# ==============================================================================
def create_safety_snapshot():
    if not config.DB_FILE.exists():
        log.info("ℹ️ No existing Vault found. Skipping backup.")
        return True

    backup_dir = config.DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"quant_strategy_BACKUP_{timestamp}.duckdb"
    backup_path = backup_dir / backup_name

    try:
        log.info(f"🛡️ INITIATING SAFETY SNAPSHOT: {backup_name}")
        shutil.copy2(config.DB_FILE, backup_path)
        log.info("✅ Snapshot secured.")
        return True
    except Exception as e:
        log.error(f"❌ SNAPSHOT FAILED: {e}")
        return False

# ==============================================================================
# 4. SCHEMA DEFINITION
# ==============================================================================
def initialize_database():
    if not create_safety_snapshot():
        log.error("⛔ ABORTING: Backup failed. Database untouched.")
        return

    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # [EXISTING TABLES REMAIN UNTOUCHED - OMITTED FOR BREVITY BUT PRESUMED HERE]
    # For completeness of the file, we re-verify them:
    
    con.execute(f"""
    CREATE TABLE IF NOT EXISTS {TBL_INDICES} (
        datetime_utc TIMESTAMP NOT NULL,
        ticker VARCHAR NOT NULL,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
        PRIMARY KEY (datetime_utc, ticker)
    )""")
    
    con.execute(f"CREATE TABLE IF NOT EXISTS {TBL_RISK_FREE} (date DATE, rate DOUBLE, PRIMARY KEY (date))")
    
    con.execute(f"""
    CREATE TABLE IF NOT EXISTS {TBL_MACRO_FLOW} (
        date DATE, 
        flow_bias VARCHAR, 
        bull_pct DOUBLE, 
        bear_pct DOUBLE, 
        PRIMARY KEY (date)
    )""")
    
    con.execute(f"""
    CREATE TABLE IF NOT EXISTS {TBL_SIM_LOG} (
        entry_time TIMESTAMP, 
        exit_time TIMESTAMP,
        ticker VARCHAR, 
        net_pnl DOUBLE, 
        return_pct DOUBLE, 
        reason VARCHAR, 
        entry_price DOUBLE, 
        exit_price DOUBLE,
        action VARCHAR,
        quantity DOUBLE,
        source_id VARCHAR,
        status VARCHAR
    )""")
    
    con.execute(f"""
    CREATE TABLE IF NOT EXISTS {TBL_RH_LEDGER} (
        source_id VARCHAR PRIMARY KEY,
        entry_time_utc TIMESTAMP,
        action VARCHAR,
        root VARCHAR,
        strike DOUBLE,
        option_right VARCHAR,
        expiry_date DATE,
        quantity DOUBLE,
        fill_price DOUBLE,
        net_pnl DOUBLE,
        fees DOUBLE,
        status VARCHAR,
        opra_code VARCHAR
    )""")

    # --- NEW: CONTEXTUAL SIGNAL LOG ---
    log.info(f"🔨 Initializing: {TBL_SIGNAL_LOG}")
    con.execute(f"""
    CREATE TABLE IF NOT EXISTS {TBL_SIGNAL_LOG} (
        timestamp_utc TIMESTAMP,
        ticker VARCHAR,
        signal_type VARCHAR,        -- BULL_FRACTAL / BEAR_FRACTAL
        vix_value DOUBLE,
        rsi_value DOUBLE,
        market_regime VARCHAR,      -- From ChopGuard (TREND/CHOP)
        flow_bias VARCHAR,          -- From MacroFlow (BULL/BEAR)
        meta_data VARCHAR,          -- Raw reason string
        PRIMARY KEY (timestamp_utc, ticker)
    )""")

    tables = con.execute("SHOW TABLES").fetchall()
    table_names = [t[0] for t in tables]
    log.info(f"✅ Database Schema Verified. Tables: {table_names}")
    con.close()

if __name__ == "__main__":
    print("\n⚠️  SYSTEM ALERT ⚠️")
    print("This script will Initialize/Verify the Vault Schema.")
    confirm = input("Type 'DEPLOY' to proceed: ")
    if confirm == "DEPLOY":
        initialize_database()