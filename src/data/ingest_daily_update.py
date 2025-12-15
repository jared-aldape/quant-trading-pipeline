import pandas as pd
import duckdb
import sys
import os
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

CSV_PATH = ROOT_DIR / "data" / "rh_options_export.csv"
ASSUMED_YEAR = 2025 

def parse_rh_timestamp(ts_str):
    """Parses RH format '12/9, 6:56 AM PST' -> datetime object"""
    try:
        if not isinstance(ts_str, str): return None
        clean_str = ts_str.replace(" PST", "").replace(" PDT", "")
        dt = datetime.strptime(f"{ASSUMED_YEAR}, {clean_str}", "%Y, %m/%d, %I:%M %p")
        return dt
    except:
        return None

def ingest_update():
    print(f"🌊 READING FULL-SPECTRUM IMPORT: {CSV_PATH.name}")
    
    if not CSV_PATH.exists():
        print(f"❌ ERROR: Could not find {CSV_PATH}")
        return

    # 1. LOAD CSV
    df = pd.read_csv(CSV_PATH)
    if 'status' in df.columns:
        df = df[df['status'] == 'Filled'].copy()
    
    # Process Oldest -> Newest
    df = df.iloc[::-1] 

    # 2. CONNECT TO LEDGER
    con = duckdb.connect(str(config.DB_FILE))
    
    # --- SCHEMA MIGRATION ---
    # Since we are changing the schema to capture ALL fields, we DROP the old table
    # to prevent "Column Count Mismatch" errors. We have the CSV source, so we can rebuild.
    print("♻️  REBUILDING LEDGER SCHEMA...")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_SIM_LOG}")
    
    # Create the 'Full Spectrum' Table
    con.execute(f"""
        CREATE TABLE {config.TBL_SIM_LOG} (
            entry_time TIMESTAMP, 
            ticker VARCHAR,        -- Underlying (XSP)
            full_ticker VARCHAR,   -- Reconstructed (XSP Call 450)
            asset_class VARCHAR,
            action VARCHAR,        -- Buy/Sell
            type VARCHAR,          -- Call/Put
            strike DOUBLE,
            exp_date VARCHAR,
            status VARCHAR,
            quantity INTEGER,
            price DOUBLE,          -- Avg Price
            fees DOUBLE,
            net_cashflow DOUBLE,   -- Calculated (+/-)
            raw_header VARCHAR,    -- Original Description
            reason VARCHAR         -- Source Tag
        )
    """)

    new_count = 0

    print("🔍 INGESTING DATA...")

    for _, row in df.iterrows():
        # Parse
        dt = parse_rh_timestamp(row['filled_at'])
        if not dt: continue

        action = row['action'].upper()
        qty = int(row['quantity'])
        price = float(row['price'])
        fees = float(row['fees'])
        
        # Logic: Buy = Negative Cashflow, Sell = Positive
        multiplier = -1 if action == 'BUY' else 1
        net_val = (price * qty * 100 * multiplier) - fees
        
        # Ticker Construction
        ticker_sym = row['ticker']
        full_ticker = f"{row['ticker']} {row['type']} {row['strike']}"
        
        # INSERT (No dedup needed on full rebuild, logic handles chronological insert)
        con.execute(f"""
            INSERT INTO {config.TBL_SIM_LOG} VALUES 
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dt,
            ticker_sym,
            full_ticker,
            row.get('asset_class', 'Option'),
            action,
            row['type'],
            row['strike'],
            row['exp_date'],
            row['status'],
            qty,
            price,
            fees,
            net_val,
            row['raw_header'],
            "USER_IMPORT_CSV"
        ))
        
        new_count += 1

    con.close()
    
    print(f"✅ LEDGER REBUILT.")
    print(f"📥 Total Rows: {new_count}")

if __name__ == "__main__":
    ingest_update()