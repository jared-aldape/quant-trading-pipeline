import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def mine_strike_efficiency():
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. Fetch all signals
    signals = con.execute("SELECT * FROM trade_manifest").df()
    signals['entry_timestamp_utc'] = pd.to_datetime(signals['entry_timestamp_utc'], unit='ms')
    
    # Define our Strike Tiers
    # +1 = Near OTM, +3 = Mid OTM, +5 = Deep OTM ("Lottery")
    tiers = [1, 2, 3, 5]
    strike_results = {t: [] for t in tiers}

    print(f"🕵️ Mining Alpha across {len(signals)} signals for Strike Efficiency...")

    for row in signals.itertuples():
        entry_time = row.entry_timestamp_utc
        entry_px_xsp = float(row.xsp_price)
        op_type = 'C' if 'CALL' in row.trade_type else 'P'
        
        for t in tiers:
            # Select the specific Strike Tier
            q = f"""
                WITH RankedOptions AS (
                    SELECT ticker, close, 
                    ABS(CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 - {entry_px_xsp}) as dist
                    FROM options_1m 
                    WHERE datetime_utc = '{entry_time}' 
                    AND SUBSTRING(ticker, 10, 1) = '{op_type}'
                    AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 {' > ' if op_type == 'C' else ' < '} {entry_px_xsp}
                )
                SELECT ticker, close FROM RankedOptions ORDER BY dist ASC LIMIT 1 OFFSET {t-1}
            """
            
            c_df = con.execute(q).df()
            if c_df.empty: continue
            
            entry_prem = c_df.iloc[0]['close']
            ticker = c_df.iloc[0]['ticker']
            
            # Track price action for 4 hours
            track = con.execute(f"SELECT high FROM options_1m WHERE ticker='{ticker}' AND datetime_utc > '{entry_time}' LIMIT 240").df()
            if track.empty: continue
            
            max_up = ((track['high'].max() - entry_prem) / entry_prem) * 100
            strike_results[t].append(max_up)

    con.close()
    
    print("\n" + "="*70)
    print("📊 STRIKE EFFICIENCY REPORT: WHICH TIER REWARDS THE RISK?")
    print("="*70)
    
    for t in tiers:
        data = np.array(strike_results[t])
        win_30 = (len(data[data >= 30]) / len(data)) * 100
        win_100 = (len(data[data >= 100]) / len(data)) * 100
        print(f"Tier +{t} OTM:")
        print(f"   - Median Max Upside: {np.median(data):.1f}%")
        print(f"   - Prob. of +30% ROI: {win_30:.1f}%")
        print(f"   - Prob. of +100% ROI: {win_100:.1f}%")
        print("-" * 40)
    print("="*70)

if __name__ == "__main__":
    mine_strike_efficiency()