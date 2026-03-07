import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
except ImportError:
    print("❌ CRITICAL: Could not import config. Run from project root.")
    sys.exit(1)

# ==============================================================================
# 2. FREQUENCY ANALYSIS ENGINE
# ==============================================================================
def analyze_frequency(df, time_col):
    """Calculates the operational cadence (frequency) of the data."""
    if df.empty or len(df) < 2:
        return "Insufficient Data"
    
    # Ensure datetime format
    df[time_col] = pd.to_datetime(df[time_col])
    
    # Calculate time difference between consecutive rows
    diffs = df[time_col].diff().abs().dropna()
    
    if diffs.empty:
        return "Unknown"
        
    # Get the most common interval (mode) in seconds
    mode_seconds = diffs.dt.total_seconds().mode()[0]
    
    if mode_seconds == 60:
        return "1-Minute (High-Resolution)"
    elif mode_seconds == 300:
        return "5-Minute (Micro-Fractal)"
    elif mode_seconds == 3600:
        return "1-Hour (Macro-Fractal)"
    elif mode_seconds == 86400:
        return "1-Day (Daily/Macro)"
    else:
        return f"{int(mode_seconds)} Seconds (Irregular/Event-Driven)"

# ==============================================================================
# 3. VAULT AUDIT PROTOCOL
# ==============================================================================
def audit_database():
    print("\n" + "="*80)
    print(f"🛡️  QUANT OS VAULT AUDIT PROTOCOL (FREQUENCY & SCHEMA)")
    print(f"    Target: {config.DB_FILE}")
    print("="*80)

    if not config.DB_FILE.exists():
        print(f"❌ CRITICAL: Database file not found at {config.DB_FILE}")
        return

    try:
        # Open in read-only to avoid locking conflicts with the active pipeline
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        
        if not tables:
            print("⚠️  Database is empty. No tables found.")
            con.close()
            return

        for tbl in tables:
            print(f"\n📊 TABLE: {tbl.upper()}")
            print("-" * 80)
            
            # 1. SCHEMA & TIME COLUMN DETECTION
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                cols = [x[0] for x in con.execute(f"DESCRIBE {tbl}").fetchall()]
                date_col = next((c for c in cols if 'time' in c or 'date' in c), None)
                
                print(f"   ROWS: {count:,}")
                
                if date_col:
                    # 2. FREQUENCY & BOUNDARIES
                    max_date = con.execute(f"SELECT MAX({date_col}) FROM {tbl}").fetchone()[0]
                    min_date = con.execute(f"SELECT MIN({date_col}) FROM {tbl}").fetchone()[0]
                    
                    # Pull a sample to determine frequency (last 1000 rows for accuracy)
                    df_sample = con.execute(f"SELECT {date_col} FROM {tbl} ORDER BY {date_col} DESC LIMIT 1000").df()
                    frequency_str = analyze_frequency(df_sample, date_col)
                    
                    print(f"   CADENCE: {frequency_str}")
                    print(f"   RANGE: {min_date}  ->  {max_date}")
                else:
                    print("   CADENCE: Static/Non-Temporal Table")
            except Exception as e:
                print(f"   ⚠️ Metadata Error: {e}")

            # 3. STRUCTURAL PREVIEW (The "Look")
            print("\n   DATA PREVIEW (Last 3 Records):")
            try:
                if date_col:
                    tail = con.execute(f"SELECT * FROM {tbl} ORDER BY {date_col} DESC LIMIT 3").df()
                else:
                    tail = con.execute(f"SELECT * FROM {tbl} LIMIT 3").df()
                print(tail.to_string(index=False))
            except Exception as e:
                print(f"   ⚠️ Could not fetch data preview: {e}")

        con.close()
        print("\n" + "="*80)
        print("✅ DEEP AUDIT COMPLETE. System Integrity Nominal.")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")

if __name__ == "__main__":
    audit_database()