import sys
import duckdb
import pandas as pd
from pathlib import Path

# Path Setup
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config
from src.core import engine_backtest

def run_direct_diagnostic():
    print(f"🕵️ DIRECT ENGINE DIAGNOSTIC")
    print(f"--------------------------------------------------")
    
    if not config.DB_FILE.exists():
        print("❌ CRITICAL: Database file missing.")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)

    # 1. INSPECT MANIFEST (The Signals)
    print("\n[1] Inspecting Signals (Manifest)...")
    manifest = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} LIMIT 3").df()
    if manifest.empty:
        print("❌ Manifest is EMPTY. No signals to trade.")
        return
    else:
        print(f"✅ Found {len(manifest)} sample signals.")
        print(f"   Sample Price (XSP): {manifest.iloc[0]['xsp_price']}")
        print(f"   Sample Type: {manifest.iloc[0]['trade_type']}")

    # 2. INSPECT OPTIONS (The Data)
    print("\n[2] Inspecting Option Chain (Data)...")
    options = con.execute(f"SELECT * FROM {config.TBL_OPTIONS} LIMIT 3").df()
    if options.empty:
        print("❌ Option Table is EMPTY. Ingestion failed.")
        return
    else:
        print(f"✅ Found {len(options)} sample option bars.")
        print(f"   Sample Ticker: {options.iloc[0]['ticker']}")
        print(f"   Sample Time: {options.iloc[0]['datetime_utc']}")

    # 3. TEST MATCHING LOGIC (The Link)
    print("\n[3] Testing Signal -> Ticker -> Price Link...")
    
    row = manifest.iloc[0]
    row_date = pd.to_datetime(row['date'])
    ticker = engine_backtest.reconstruct_ticker(row['trade_type'], row['xsp_price'], row_date)
    
    print(f"   Signal ID: {row_date} {row['trade_type']}")
    print(f"   Target Ticker: {ticker}")
    
    # Check if this ticker exists in DB
    exists = con.execute(f"SELECT count(*) FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}'").fetchone()[0]
    
    if exists > 0:
        print(f"   ✅ Ticker Found in DB! ({exists} bars)")
        
        # Test Price Lookup
        entry_ts = pd.Timestamp(row['entry_timestamp_utc'], unit='ms', tz='UTC')
        print(f"   Looking for price at: {entry_ts}")
        
        price, actual_time = engine_backtest.lookup_price(con, ticker, entry_ts)
        
        if price:
            print(f"   ✅ Price Found: ${price} at {actual_time}")
        else:
            print(f"   ❌ Price Lookup Failed (No data near entry time).")
    else:
        print(f"   ❌ Ticker NOT Found in DB.")
        print(f"   Debug Hint: Check if Manifest Price ({row['xsp_price']}) matches Ingested Tickers.")

    # 4. RUN FULL ENGINE
    print("\n[4] Running Full Backtest Engine (Headless)...")
    
    # Mock Args Class
    class Args:
        start_date = '2025-09-11'
        end_date = '2025-12-01'
        start_balance = 10000.0
        pos_size_pct = 0.10
        max_invest = 2000.0
        strategy_mode = 'LONG_ONLY'
        
    try:
        results = engine_backtest.run_backtest(Args)
        if not results.empty:
            print(f"✅ SUCCESS! Engine returned {len(results)} trades.")
            print(f"   Final Balance: ${results.iloc[-1]['balance']:,.2f}")
        else:
            print("⚠️ Engine ran but returned 0 trades.")
    except Exception as e:
        print(f"❌ Engine Crashed: {e}")

    con.close()

if __name__ == "__main__":
    run_direct_diagnostic()