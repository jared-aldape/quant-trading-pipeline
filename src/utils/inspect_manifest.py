import duckdb
import pandas as pd
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def inspect_system():
    print("="*60)
    print("🕵️  SYSTEM INSPECTION TOOL")
    print("="*60)

    # --- 1. DATABASE CHECK ---
    print(f"\n📡 CONNECTING TO: {config.DB_FILE}")
    
    if not config.DB_FILE.exists():
        print("❌ CRITICAL: Database file does not exist.")
        return

    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # Check if Manifest Table Exists
        tables = con.execute("SHOW TABLES").df()
        if config.TBL_MANIFEST not in tables['name'].values:
            print(f"⚠️  Table '{config.TBL_MANIFEST}' NOT FOUND. Scanner has not written any signals yet.")
        else:
            # Fetch latest signals
            query = f"""
                SELECT 
                    strftime(to_timestamp(entry_timestamp_utc / 1000), '%Y-%m-%d %H:%M:%S') as time_utc,
                    signal_type,
                    trade_type,
                    xsp_price,
                    meta_data
                FROM {config.TBL_MANIFEST}
                ORDER BY entry_timestamp_utc DESC
                LIMIT 10
            """
            df = con.execute(query).df()
            
            if df.empty:
                print("⚠️  Manifest table exists but is EMPTY.")
            else:
                print(f"✅ FOUND {len(df)} RECENT SIGNALS:\n")
                print(df.to_string(index=False))
                
        con.close()
        
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")

    # --- 2. LOG FILE CHECK ---
    print("\n" + "-"*60)
    print("📝 LATEST LOG ACTIVITY")
    print("-" * 60)
    
    log_dir = ROOT_DIR / "logs"
    if not log_dir.exists():
        print(f"❌ Log directory not found at {log_dir}")
        return

    # Find the most recent log file (usually Scanner.log)
    log_files = list(log_dir.glob("*.log"))
    if not log_files:
        print("⚠️  No log files found.")
        return
        
    # Sort by modification time to get the latest
    latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
    print(f"📂 Reading: {latest_log.name}\n")
    
    try:
        with open(latest_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Print last 15 lines
            for line in lines[-15:]:
                print(line.strip())
    except Exception as e:
        print(f"❌ Error reading log: {e}")

    print("\n" + "="*60)

if __name__ == "__main__":
    inspect_system()