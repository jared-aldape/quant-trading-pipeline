import sys
import duckdb
import pandas as pd
import yfinance as yf
import pytz
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def backfill_es_futures():
    con = duckdb.connect(str(config.DB_FILE))
    
    print("📡 Fetching high-resolution S&P 500 Futures (ES=F) data...")
    
    # yfinance only allows 1m data for the last 7 days
    es = yf.download("ES=F", period="7d", interval="1m", progress=False, auto_adjust=True)
    
    if es.empty:
        print("❌ Failed to download ES=F data.")
        return
        
    # Formatting to match our indices_1m table
    es = es.reset_index()
    # Handle yfinance multi-index columns if present
    if isinstance(es.columns, pd.MultiIndex):
        es.columns = [c[0] if c[0] != 'Datetime' else 'Datetime' for c in es.columns]
        
    es = es.rename(columns={
        'Datetime': 'datetime_utc',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    })
    
    # Ensure UTC timezone
    if es['datetime_utc'].dt.tz is None:
        es['datetime_utc'] = es['datetime_utc'].dt.tz_localize('UTC')
    else:
        es['datetime_utc'] = es['datetime_utc'].dt.tz_convert('UTC')
        
    es['ticker'] = 'ES'
    
    print(f"✅ Downloaded {len(es)} 1-minute candles for ES.")
    
    # ⚡ THE FIX: Explicit Column Alignment
    try:
        con.execute("DELETE FROM indices_1m WHERE ticker = 'ES'") # Clear old if any
        con.register('es_temp', es)
        
        # Interrogate the database for its exact column names
        db_cols_df = con.execute("DESCRIBE indices_1m").df()
        db_cols = db_cols_df['column_name'].tolist()
        
        # Only insert columns that actually exist in the DB, in the exact order
        insert_cols = [c for c in db_cols if c in es.columns]
        cols_str = ", ".join(insert_cols)
        
        con.execute(f"INSERT INTO indices_1m ({cols_str}) SELECT {cols_str} FROM es_temp")
        print("💾 ES Futures successfully injected into the Vault (indices_1m).")
    except Exception as e:
        print(f"❌ DB Write Error: {e}")

    # ==========================================================
    # 🔍 INSTANT DIVERGENCE TEST (Last 7 Days)
    # ==========================================================
    print("\n" + "="*70)
    print("🔍 RE-RUNNING DIVERGENCE ENGINE ON NEW FUTURES DATA")
    print("="*70)
    
    try:
        # Find the biggest XSP drop in the LAST 7 DAYS (where we have ES data)
        q_drop = """
            SELECT datetime_utc, (high - low) as candle_range
            FROM indices_1m
            WHERE ticker = 'XSP' 
            AND datetime_utc >= current_date - interval 7 day
            ORDER BY candle_range DESC
            LIMIT 1
        """
        drop_result = con.execute(q_drop).fetchone()
        
        if drop_result:
            biggest_drop_dt = drop_result[0]
            
            q_es_xsp = f"""
                SELECT 
                    CAST(e.datetime_utc AS STRING) as time_utc,
                    e.close as es_price,
                    x.close as xsp_price,
                    v.close as vix_price
                FROM indices_1m e
                LEFT JOIN indices_1m x ON e.datetime_utc = x.datetime_utc AND x.ticker = 'XSP'
                LEFT JOIN indices_1m v ON e.datetime_utc = v.datetime_utc AND v.ticker = 'VIX'
                WHERE e.ticker = 'ES'
                AND e.datetime_utc >= '{biggest_drop_dt}'::TIMESTAMP - INTERVAL 3 MINUTE
                AND e.datetime_utc <= '{biggest_drop_dt}'::TIMESTAMP + INTERVAL 3 MINUTE
                ORDER BY e.datetime_utc ASC
            """
            es_data = con.execute(q_es_xsp).df()
            
            print(f"💥 Volatility Event Found: {biggest_drop_dt} UTC")
            print(es_data.to_string(index=False))
            
            # Simple lag calculation
            print("\n🧠 ARCHITECT ANALYSIS:")
            print("Look at the rows right before the Volatility Event.")
            print("Did the 'es_price' start dropping 1-2 minutes BEFORE the 'xsp_price' dropped?")
    except Exception as e:
        print(f"Error querying divergence: {e}")
        
    con.close()

if __name__ == "__main__":
    backfill_es_futures()