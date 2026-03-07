import sys
import duckdb
import pandas as pd
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def audit_intraday_seasonality():
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    print("\n" + "="*80)
    print("🔬 AUDITING INSTITUTIONAL INTRADAY SEASONALITY (XSP)")
    print("="*80)
    
    # We want to group by 10-minute blocks between 14:30 UTC (06:30 PST) and 18:30 UTC (10:30 PST)
    query = """
        WITH TimeBlocks AS (
            SELECT 
                EXTRACT(hour FROM datetime_utc) as hr_utc,
                EXTRACT(minute FROM datetime_utc) as mn_utc,
                (EXTRACT(hour FROM datetime_utc) - 8) as hr_pst, -- Rough conversion for labels
                high - low as candle_range
            FROM indices_1m
            WHERE ticker = 'XSP'
            AND EXTRACT(hour FROM datetime_utc) BETWEEN 14 AND 18
        ),
        GroupedBlocks AS (
            SELECT 
                hr_utc,
                FLOOR(mn_utc / 10) * 10 as block_10m,
                AVG(candle_range) as avg_volatility
            FROM TimeBlocks
            GROUP BY hr_utc, FLOOR(mn_utc / 10) * 10
        )
        SELECT 
            hr_utc, 
            block_10m as mn_utc_start,
            avg_volatility
        FROM GroupedBlocks
        ORDER BY hr_utc ASC, block_10m ASC
    """
    
    df = con.execute(query).df()
    
    if df.empty:
        print("No XSP data found for the specified time blocks.")
        return

    # Formatting the output to show PST time blocks
    print(f"{'TIME BLOCK (PST)':<20} | {'TIME BLOCK (UTC)':<20} | {'AVG VOLATILITY (XSP POINTS)':<25} | {'OBSERVATION'}")
    print("-" * 90)
    
    for _, row in df.iterrows():
        hr_utc = int(row['hr_utc'])
        mn_utc = int(row['mn_utc_start'])
        vol = row['avg_volatility']
        
        # PST conversion (UTC - 8 for winter, simplistic but works for this visualization)
        hr_pst = hr_utc - 8
        
        time_pst = f"{hr_pst:02d}:{mn_utc:02d} - {hr_pst:02d}:{mn_utc+9:02d}"
        time_utc = f"{hr_utc:02d}:{mn_utc:02d} - {hr_utc:02d}:{mn_utc+9:02d}"
        
        # Adding your observations as tags
        tag = ""
        if hr_pst == 6 and mn_utc >= 40:
            tag = "🔥 THE TURN / MORNING DRIVE"
        elif hr_pst == 7:
            tag = "🧊 THE NEUTRAL CHOP (IV DECAY ZONE)"
        elif hr_pst == 8 and mn_utc <= 10:
            tag = "⚡ THE 08:00 MOVEMENT"
        elif hr_pst == 9 and mn_utc >= 30:
            tag = "🌊 THE 09:30 AFTERNOON INITIATION"
            
        # Draw a visual bar for the volatility
        bar_length = int(vol * 15) # Scaling factor for visualization
        visual_bar = "█" * bar_length
            
        print(f"{time_pst:<20} | {time_utc:<20} | {vol:.4f} {visual_bar:<15} | {tag}")

    print("="*90)
    con.close()

if __name__ == "__main__":
    audit_intraday_seasonality()