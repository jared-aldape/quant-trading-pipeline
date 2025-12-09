import sys
import os
import duckdb
import shutil
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.7: PATH CONSTITUTION
# ==============================================================================
# File: src/data/db_schema.py
# Root: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SchemaManager")

# ==============================================================================
# 2. SAFETY PROTOCOLS
# ==============================================================================
def create_safety_snapshot():
    """
    Creates a timestamped copy of the database before any destructive operations.
    Returns True if backup was successful or if no DB existed.
    """
    if not config.DB_FILE.exists():
        log.info("ℹ️ No existing Vault found. Skipping backup.")
        return True

    backup_dir = config.DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"quant_strategy_BACKUP_{timestamp}.duckdb"
    backup_path = backup_dir / backup_name

    try:
        log.info(f"🛡️ INITIATING SAFETY SNAPSHOT...")
        shutil.copy2(config.DB_FILE, backup_path)
        log.info(f"✅ SNAPSHOT SECURED: {backup_path}")
        return True
    except Exception as e:
        log.critical(f"❌ BACKUP FAILED: {e}")
        log.critical("🛑 OPERATION ABORTED. THE VAULT WAS NOT TOUCHED.")
        return False

# ==============================================================================
# 3. SCHEMA DEFINITION
# ==============================================================================
def initialize_database():
    # STEP 1: ENFORCE BACKUP
    if not create_safety_snapshot():
        return # Hard Stop if backup fails

    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # ------------------------------------------------------------------
    # 1. MARKET INDICES (The Truth)
    # ------------------------------------------------------------------
    log.info(f"🔨 Initializing: {config.TBL_INDICES}")
    con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, PRIMARY KEY (datetime_utc, ticker))")
    
    log.info(f"🔨 Initializing: {config.TBL_IRX}")
    con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_IRX} (date DATE, ticker VARCHAR, rate DOUBLE, PRIMARY KEY (date))")

    log.info(f"🔨 Initializing: {config.TBL_FUTURES}")
    con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_FUTURES} (datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, PRIMARY KEY (datetime_utc, ticker))")

    # ------------------------------------------------------------------
    # 2. OPTION VEHICLE (The Product)
    # ------------------------------------------------------------------
    log.info(f"🔨 Initializing: {config.TBL_OPTIONS}")
    con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_OPTIONS} (datetime_utc TIMESTAMP, ticker VARCHAR, expiration DATE, strike DOUBLE, type VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, iv DOUBLE, delta DOUBLE, gamma DOUBLE, vega DOUBLE, theta DOUBLE, underlying_price DOUBLE, risk_free_rate DOUBLE, PRIMARY KEY (datetime_utc, ticker))")

    # ------------------------------------------------------------------
    # 3. STRATEGY DATA (Core Engine)
    # ------------------------------------------------------------------
    log.info(f"🔨 Initializing: {config.TBL_MANIFEST}")
    con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_MANIFEST} (entry_timestamp_utc BIGINT, date DATE, signal_type VARCHAR, xsp_price DOUBLE, trade_type VARCHAR, meta_data VARCHAR, allocation_pct DOUBLE, PRIMARY KEY (entry_timestamp_utc))")
    
    log.info(f"🔨 Initializing: {config.TBL_MACRO_FLOW}")
    con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_MACRO_FLOW} (date DATE, flow_bias VARCHAR, bull_pct DOUBLE, bear_pct DOUBLE, PRIMARY KEY (date))")
    
    # --- SIMULATION LOG (UPDATED) ---
    log.info(f"🔨 Re-Initializing: {config.TBL_SIM_LOG}")
    # We drop and recreate this specific table to ensure the schema update is applied
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_SIM_LOG}")
    con.execute(f"""
    CREATE TABLE {config.TBL_SIM_LOG} (
        entry_time TIMESTAMP, 
        exit_time TIMESTAMP,   -- <--- NEW COLUMN ADDED HERE
        ticker VARCHAR, 
        net_pnl DOUBLE, 
        return_pct DOUBLE, 
        reason VARCHAR, 
        entry_price DOUBLE, 
        exit_price DOUBLE
    )""")
    
    # ------------------------------------------------------------------
    # 4. VERIFICATION
    # ------------------------------------------------------------------
    tables = con.execute("SHOW TABLES").fetchall()
    table_names = [t[0] for t in tables]
    log.info(f"✅ Database Initialized. Tables: {table_names}")
    con.close()

if __name__ == "__main__":
    print("\n⚠️  CRITICAL WARNING ⚠️")
    print("This script will RESET the Vault schema.")
    print("A SAFETY SNAPSHOT will be created automatically in /data/backups/.")
    confirm = input("Type 'CONFIRM' to proceed: ")
    
    if confirm == "CONFIRM":
        initialize_database()
    else:
        print("❌ Aborted.")