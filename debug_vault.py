import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# PATH CONFIGURATION (ROOT EXECUTION)
# ==============================================================================
# Current: QUANT-TRADING-PIPELINE/debug_vault.py
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils import config

def audit_vault():
    print(f"\n🕵️ AUDITING VAULT: {config.DB_FILE}")
    print(f"📍 Root Path: {ROOT_DIR}")
    
    if not config.DB_FILE.exists():
        print("❌ CRITICAL: Database file not found on disk!")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. List All Tables
        tables = con.execute("SHOW TABLES").fetchall()
        print(f"\n📋 TABLES FOUND: {len(tables)}")
        
        sim_log_exists = False
        for t in tables:
            t_name = t[0]
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {t_name}").fetchone()[0]
                print(f"   - {t_name:<25} : {count:>5} rows")
                if t_name == config.TBL_SIM_LOG:
                    sim_log_exists = True
            except:
                print(f"   - {t_name:<25} : ERROR READING")

        # 2. Deep Dive into Simulation Log
        if sim_log_exists:
            print(f"\n🔬 INSPECTING {config.TBL_SIM_LOG}:")
            df = con.execute(f"SELECT * FROM {config.TBL_SIM_LOG} LIMIT 5").df()
            if df.empty:
                print("   ⚠️  Table exists but is ZERO rows (Ghost Data confirmed).")
            else:
                print(f"   ✅ Data detected. Columns: {list(df.columns)}")
                print(df.head(3).to_string())
        else:
            print(f"\n❌ {config.TBL_SIM_LOG} table does NOT exist.")

        con.close()

    except Exception as e:
        print(f"\n❌ AUDIT FAILED: {e}")

if __name__ == "__main__":
    audit_vault()