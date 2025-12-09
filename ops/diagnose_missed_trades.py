import sys
import duckdb
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytz

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def diagnose():
    print(f"🕵️ DIAGNOSTIC v2 (TZ-Aware): {config.DB_FILE}\n")
    
    if not config.DB_FILE.exists():
        print("❌ Database not found.")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)

    print("--- TRACING SIGNAL ALIGNMENT ---")
    signals = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc ASC LIMIT 5").df()

    for i, row in signals.iterrows():
        # 1. Parse Signal Time (Stored as UTC Epoch in DB)
        ts_ms = row['entry_timestamp_utc']
        # FORCE UTC interpretation
        signal_dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        
        # 2. Reconstruct Ticker
        date_fmt = pd.to_datetime(row['date']).strftime('%y%m%d')
        type_char = 'C' if 'CALL' in row['trade_type'].upper() else 'P'
        like_pattern = f"O:XSP{date_fmt}{type_char}%"
        
        print(f"\n🔍 SIGNAL #{i+1}")
        print(f"   Stored Epoch: {ts_ms}")
        print(f"   UTC Time:     {signal_dt_utc.strftime('%Y-%m-%d %H:%M:%S')} (The Truth)")
        print(f"   NY Time:      {signal_dt_utc.astimezone(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')} (For Humans)")
        print(f"   Target:       {row['trade_type']} @ {row['xsp_price']}")

        # 3. Check Option Data (In UTC)
        # We look for ANY data for this contract on this day
        opt_check = con.execute(f"""
            SELECT ticker, MIN(datetime_utc) as start_utc, MAX(datetime_utc) as end_utc
            FROM {config.TBL_OPTIONS}
            WHERE ticker LIKE '{like_pattern}'
            GROUP BY ticker
        """).df()
        
        if opt_check.empty:
            print(f"   ❌ DATA MISSING: No options found for pattern '{like_pattern}'")
        else:
            print(f"   ✅ DATA FOUND: {len(opt_check)} contracts.")
            
            # 4. Strict Time Check
            # We explicitly format the SQL query to use the UTC timestamp string
            search_start = (signal_dt_utc - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
            search_end = (signal_dt_utc + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
            
            valid_contract = False
            for _, opt in opt_check.iterrows():
                ticker = opt['ticker']
                # Check for bars specifically in the signal window
                bars = con.execute(f"""
                    SELECT * FROM {config.TBL_OPTIONS}
                    WHERE ticker = '{ticker}'
                    AND datetime_utc BETWEEN '{search_start}' AND '{search_end}'
                """).df()
                
                if not bars.empty:
                    print(f"      Matched: {ticker} has data at {bars.iloc[0]['datetime_utc']} UTC")
                    valid_contract = True
                    break
            
            if valid_contract:
                print("   ✨ ALIGNMENT CONFIRMED: Signal Time matches Option Data.")
            else:
                print(f"   ⚠️ OFFSET ERROR: Data exists ({opt['start_utc']} UTC) but not at Signal Time ({signal_dt_utc} UTC).")

    con.close()

if __name__ == "__main__":
    diagnose()