import duckdb
import pandas as pd
import sys
from pathlib import Path

# PATH SETUP
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def inspect_database():
    print(f"🕵️  INSPECTING VAULT: {config.DB_FILE}")
    
    if not config.DB_FILE.exists():
        print("❌ Database file not found!")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. LIST ALL TABLES
        print("\n" + "="*50)
        print("📂 EXISTING TABLES")
        print("="*50)
        tables = con.execute("SHOW TABLES").fetchall()
        if not tables:
            print("   (No tables found)")
        
        for t in tables:
            table_name = t[0]
            count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"   • {table_name:<20} | Rows: {count:,}")

        # 2. DEEP DIVE: INDICES_1M (The Problem Child)
        target_table = config.TBL_INDICES  # indices_1m
        if (target_table,) in tables:
            print("\n" + "="*50)
            print(f"🔬 DIAGNOSTICS: {target_table}")
            print("="*50)
            
            # Get Columns and Types
            schema_info = con.execute(f"PRAGMA table_info('{target_table}')").fetchall()
            print(f"   {'CID':<4} {'NAME':<15} {'TYPE':<15} {'NULL?':<10}")
            print("   " + "-"*45)
            
            ticker_type = "UNKNOWN"
            for col in schema_info:
                # col structure: (cid, name, type, notnull, dflt_value, pk)
                cid, name, dtype, notnull, _, _ = col
                print(f"   {cid:<4} {name:<15} {dtype:<15} {notnull:<10}")
                if name == 'ticker':
                    ticker_type = dtype

            print("\n" + "-"*50)
            if "INT" in ticker_type.upper():
                print(f"❌ CRITICAL ISSUE: 'ticker' column is {ticker_type}!")
                print("   Run 'src/data/repair_indices.py' immediately.")
            elif "VARCHAR" in ticker_type.upper():
                print(f"✅ STATUS OK: 'ticker' column is {ticker_type}.")
            else:
                print(f"⚠️ STATUS WARNING: 'ticker' column is {ticker_type} (Expected VARCHAR).")
            print("-"*50)

        con.close()

    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")

if __name__ == "__main__":
    inspect_database()