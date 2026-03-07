import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def extract_architect_data():
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    print("\n" + "="*70)
    print("🔍 MISSION 1: FUTURES-LEAD DIVERGENCE (ES vs XSP vs VIX)")
    print("="*70)
    
    # 1. Find the exact minute of the largest XSP drop/spike in the database
    try:
        q_drop = """
            SELECT datetime_utc, (high - low) as candle_range
            FROM indices_1m
            WHERE ticker = 'XSP'
            ORDER BY candle_range DESC
            LIMIT 1
        """
        drop_result = con.execute(q_drop).fetchone()
        
        if drop_result:
            biggest_drop_dt = drop_result[0]
            
            # Pull 5 minutes before and 5 minutes after the event
            q_es_xsp = f"""
                SELECT 
                    CAST(e.datetime_utc AS STRING) as time_utc,
                    e.close as es_price,
                    x.close as xsp_price,
                    v.close as vix_price
                FROM indices_1m e
                LEFT JOIN indices_1m x ON e.datetime_utc = x.datetime_utc AND x.ticker = 'XSP'
                LEFT JOIN indices_1m v ON e.datetime_utc = v.datetime_utc AND v.ticker = 'VIX'
                WHERE e.ticker IN ('ES', 'ES=F', '/ES') -- Checking common Future tickers
                AND e.datetime_utc >= '{biggest_drop_dt}'::TIMESTAMP - INTERVAL 5 MINUTE
                AND e.datetime_utc <= '{biggest_drop_dt}'::TIMESTAMP + INTERVAL 5 MINUTE
                ORDER BY e.datetime_utc ASC
            """
            es_data = con.execute(q_es_xsp).df()
            if es_data.empty:
                print(f"⚠️ Volatility Event found at {biggest_drop_dt}, but no 'ES' futures data found at that timestamp.")
                print("Checking available tickers in indices_1m...")
                tickers = con.execute("SELECT DISTINCT ticker FROM indices_1m").df()
                print(f"Available Tickers: {tickers['ticker'].tolist()}")
            else:
                print(f"💥 Volatility Event Found: {biggest_drop_dt} UTC")
                print(es_data.to_string(index=False))
        else:
            print("No XSP data found in indices_1m.")
            
    except Exception as e:
        print(f"Error extracting ES data: {e}")

    print("\n" + "="*70)
    print("📈 MISSION 2: JAN vs FEB STRIKE EFFICIENCY (TIER-3 FOCUS)")
    print("="*70)
    
    try:
        signals = con.execute("SELECT * FROM trade_manifest").df()
        if not signals.empty:
            signals['entry_timestamp_utc'] = pd.to_datetime(signals['entry_timestamp_utc'], unit='ms')
            signals['month'] = signals['entry_timestamp_utc'].dt.month
            
            jan_feb_signals = signals[signals['month'].isin([1, 2])]
            
            if jan_feb_signals.empty:
                print("⚠️ No signals found for January or February in trade_manifest.")
            else:
                results = {'1': [], '2': []} 
                print(f"Crunching {len(jan_feb_signals)} signals across Jan and Feb...")
                
                for row in jan_feb_signals.itertuples():
                    t_time = row.entry_timestamp_utc
                    px = float(row.xsp_price)
                    op_type = 'C' if 'CALL' in row.trade_type else 'P'
                    month = str(row.month)
                    
                    # Target Tier-3 (+3 OTM)
                    q_opt = f"""
                        WITH Ranked AS (
                            SELECT ticker, close, ABS(CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 - {px}) as dist
                            FROM options_1m
                            WHERE datetime_utc = '{t_time}' AND SUBSTRING(ticker, 10, 1) = '{op_type}'
                            AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 {' > ' if op_type == 'C' else ' < '} {px}
                        )
                        SELECT ticker, close FROM Ranked ORDER BY dist ASC LIMIT 1 OFFSET 2
                    """
                    
                    c_df = con.execute(q_opt).df()
                    if c_df.empty: continue
                    
                    entry_prem = c_df.iloc[0]['close']
                    ticker = c_df.iloc[0]['ticker']
                    
                    track = con.execute(f"SELECT high FROM options_1m WHERE ticker='{ticker}' AND datetime_utc > '{t_time}' LIMIT 240").df()
                    if track.empty: continue
                    
                    max_up = ((track['high'].max() - entry_prem) / entry_prem) * 100
                    results[month].append(max_up)

                for m_num, m_name in [('1', 'JANUARY'), ('2', 'FEBRUARY')]:
                    data = np.array(results[m_num])
                    if len(data) == 0:
                        print(f"[{m_name}]: No valid options track data found.")
                        continue
                    
                    win_30 = (len(data[data >= 30]) / len(data)) * 100
                    win_100 = (len(data[data >= 100]) / len(data)) * 100
                    
                    print(f"\n[{m_name}] TIER-3 OTM PERFORMANCE:")
                    print(f"  - Sample Size:        {len(data)} setups")
                    print(f"  - Median Max Upside:  {np.median(data):.1f}%")
                    print(f"  - Prob of +30% Win:   {win_30:.1f}%")
                    print(f"  - Prob of +100% Win:  {win_100:.1f}%")
    except Exception as e:
        print(f"Error mining strike efficiency: {e}")
        
    con.close()

if __name__ == "__main__":
    extract_architect_data()