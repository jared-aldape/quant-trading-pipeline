import sys
import duckdb
import pandas as pd
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def run_asof_divergence():
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    print("🔬 ALIGNING ASYNCHRONOUS EXCHANGE DATA (AS OF JOIN)...")
    
    # 1. Pull XSP directly around the event
    xsp = con.execute("""
        SELECT datetime_utc, close as xsp_price 
        FROM indices_1m 
        WHERE ticker = 'XSP' 
        AND datetime_utc >= '2026-03-03 14:20:00'
        AND datetime_utc <= '2026-03-03 14:40:00'
        ORDER BY datetime_utc
    """).df()
    
    # 2. Pull ES with a MASSIVE 12-hour window to catch the Timezone Ghost
    es = con.execute("""
        SELECT datetime_utc, close as es_price 
        FROM indices_1m 
        WHERE ticker = 'ES' 
        AND datetime_utc >= '2026-03-03 04:00:00'
        AND datetime_utc <= '2026-03-03 23:59:00'
        ORDER BY datetime_utc
    """).df()
    
    if es.empty:
        print("❌ ES data is completely missing for March 3rd!")
        # Let's see what dates ES DOES have
        es_dates = con.execute("SELECT MIN(datetime_utc) as first_row, MAX(datetime_utc) as last_row, COUNT(*) as total_rows FROM indices_1m WHERE ticker = 'ES'").df()
        print("\n📊 ES Data in Vault:")
        print(es_dates.to_string(index=False))
        return

    # 3. Strip Timezones to force alignment
    xsp['datetime_utc'] = pd.to_datetime(xsp['datetime_utc']).dt.tz_localize(None)
    es['datetime_utc'] = pd.to_datetime(es['datetime_utc']).dt.tz_localize(None)
    
    # 4. The Magic: "For every XSP row, find the closest ES row looking backwards"
    merged = pd.merge_asof(
        xsp, es,
        on='datetime_utc',
        direction='backward',
        tolerance=pd.Timedelta('6 hours') # Massive tolerance to prove the timezone shift
    )
    
    print("\n" + "="*70)
    print("🔍 THE ALIGNED DIVERGENCE ENGINE (MARCH 3rd EVENT)")
    print("="*70)
    
    # Filter back down to the exact drop window
    target_window = merged[(merged['datetime_utc'] >= '2026-03-03 14:27:00') & (merged['datetime_utc'] <= '2026-03-03 14:33:00')]
    print(target_window.to_string(index=False))
    
    print("\n🧠 ARCHITECT ANALYSIS:")
    print("If you see 'NaN' for ES price, the data is entirely missing for that day.")
    print("If you see the ES price, look at how it moves vs XSP. Who drops first?")
    print("="*70)
    
    con.close()

if __name__ == "__main__":
    run_asof_divergence()