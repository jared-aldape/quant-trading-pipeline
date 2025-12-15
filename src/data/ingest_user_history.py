import pandas as pd
import duckdb
import sys
import os
from datetime import datetime
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("HistoryIngest")

# CONFIGURATION
# We assume the CSV is in the 'data' folder
CSV_PATH = ROOT_DIR / "data" / "rh_options_export.csv"
ASSUMED_YEAR = 2025  # Update this if your data crosses years

def parse_rh_timestamp(ts_str):
    """
    Parses '12/9, 6:56 AM PST' -> Datetime object.
    Adds the ASSUMED_YEAR because RH exports often exclude it.
    """
    try:
        if not isinstance(ts_str, str): return None
        # Clean TZ info for parsing (we assume local/NY time usually, but RH uses PST often)
        clean_str = ts_str.replace(" PST", "").replace(" PDT", "")
        # Format: "12/9, 6:56 AM"
        dt = datetime.strptime(f"{ASSUMED_YEAR}, {clean_str}", "%Y, %m/%d, %I:%M %p")
        return dt
    except Exception as e:
        return None

def ingest():
    if not CSV_PATH.exists():
        log.error(f"❌ File not found: {CSV_PATH}")
        log.info("Please place 'rh_options_export.csv' in the /data folder.")
        return

    log.info(f"📂 Reading Ledger: {CSV_PATH.name}...")
    df = pd.read_csv(CSV_PATH)

    # 1. Filter: We only want 'Filled' orders.
    if 'status' in df.columns:
        df = df[df['status'] == 'Filled'].copy()

    # 2. Parse Timestamps
    df['entry_time'] = df['filled_at'].apply(parse_rh_timestamp)
    df = df.dropna(subset=['entry_time']) # Drop unparsable rows

    log.info(f"🔍 Found {len(df)} valid trades. Parsing financials...")

    # 3. Connect to Vault
    con = duckdb.connect(str(config.DB_FILE))
    
    # Ensure Table Exists
    # Note: Even if it exists with 9 columns, this check passes.
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_SIM_LOG} (
            entry_time TIMESTAMP, 
            ticker VARCHAR, 
            net_pnl DOUBLE, 
            return_pct DOUBLE, 
            reason VARCHAR, 
            entry_price DOUBLE, 
            exit_price DOUBLE,
            duration_mins DOUBLE
        )
    """)

    # 4. Construct Ledger Entries
    inserted = 0
    
    for _, row in df.iterrows():
        # Logic: 
        # Buy = Negative Cashflow (Debit)
        # Sell = Positive Cashflow (Credit)
        multiplier = -1 if row['action'] == 'Buy' else 1
        
        # Net PnL = (Price * Qty * 100 * Direction) - Fees
        # Note: 'fees' column in RH CSV is absolute value
        raw_val = (row['price'] * row['quantity'] * 100 * multiplier)
        net_val = raw_val - row['fees']
        
        # Ticker Construction
        full_ticker = f"{row['ticker']} {row['type']} {row['strike']}"
        
        # Deduplication Check
        check = con.execute(f"""
            SELECT count(*) FROM {config.TBL_SIM_LOG} 
            WHERE entry_time = ? AND ticker = ? AND net_pnl = ?
        """, (row['entry_time'], full_ticker, net_val)).fetchone()[0]
        
        if check == 0:
            # FIX: We explicitly list the columns we are inserting into.
            # This allows the insertion to work even if the table has extra columns (like 'id').
            con.execute(f"""
                INSERT INTO {config.TBL_SIM_LOG} 
                (entry_time, ticker, net_pnl, return_pct, reason, entry_price, exit_price, duration_mins)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['entry_time'], 
                full_ticker, 
                net_val, 
                0.0, 
                "USER_IMPORT_CSV", 
                row['price'], 
                0.0, 
                0.0
            ))
            inserted += 1

    con.close()
    log.info(f"✅ Successfully injected {inserted} trades into the Options Simulator.")
    log.info("👉 You can now view these in 'Stats Lab' under 'USER_IMPORT_CSV'.")

if __name__ == "__main__":
    ingest()