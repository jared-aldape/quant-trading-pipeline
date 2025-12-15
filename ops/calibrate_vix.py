import duckdb
import pandas as pd
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
import src.core.strat_fractal as strategy

def calibrate():
    print("🧮 VIX CALIBRATION TOOL INITIALIZED")
    print(f"🔌 Connecting to Vault: {config.DB_FILE}")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. FETCH RAW VIX
    df = con.execute(f"SELECT datetime_utc, close FROM {config.TBL_INDICES} WHERE ticker = 'VIX' ORDER BY datetime_utc").df()
    
    if df.empty:
        print("❌ CRITICAL: No VIX Data Found.")
        return

    print(f"📊 Loaded {len(df)} VIX Candles.")
    
    # 2. APPLY IDENTICAL PROCESSING (Simulate Scanner)
    df.set_index('datetime_utc', inplace=True)
    
    # Resample to 5M + FFILL (Exactly like scanner)
    df_5m = df['close'].resample('5min').ohlc()
    df_5m = df_5m[['close']].ffill() # <--- The Critical Fix
    
    # Calculate Indicators
    df_5m = strategy.calculate_macd(df_5m)
    df_5m = strategy.calculate_rsi(df_5m)
    
    # Filter for the "Live" Window (last 60 days) where you have data
    # (Assuming the last 20% of data is the high-res part)
    cutoff = int(len(df_5m) * 0.8) 
    live_df = df_5m.iloc[cutoff:]
    
    print("\n🔎 ANALYZING INDICATOR DISTRIBUTION (Last ~20% of Data)")
    print("-------------------------------------------------------")
    
    # RSI STATS
    rsi_min = live_df['rsi'].min()
    rsi_max = live_df['rsi'].max()
    rsi_avg = live_df['rsi'].mean()
    print(f"📉 RSI RANGE:  Min {rsi_min:.2f} | Max {rsi_max:.2f} | Avg {rsi_avg:.2f}")
    
    # MACD HIST STATS
    hist_min = live_df['hist'].min()
    hist_max = live_df['hist'].max()
    hist_avg = live_df['hist'].mean()
    print(f"📊 HIST RANGE: Min {hist_min:.4f} | Max {hist_max:.4f} | Avg {hist_avg:.4f}")
    
    print("\n🎯 THRESHOLD REALITY CHECK")
    print("-------------------------------------------------------")
    
    # Check current Call Thresholds
    # CALL: Hist < 0.05 AND RSI > 45
    valid_calls = live_df[ (live_df['hist'] < 0.05) & (live_df['rsi'] > 45) ]
    print(f"✅ CALL CANDIDATES (Theoretical): {len(valid_calls)} candles")
    
    # Check current Put Thresholds
    # PUT: Hist > 0.05 AND RSI < 45
    valid_puts = live_df[ (live_df['hist'] > 0.05) & (live_df['rsi'] < 45) ]
    print(f"✅ PUT CANDIDATES (Theoretical):  {len(valid_puts)} candles")
    
    print("\n💡 RECOMMENDATION:")
    if len(valid_calls) == 0:
        print("   -> Your 'Call' Histogram threshold is too low, or RSI is never > 45.")
    if len(valid_puts) == 0:
        print("   -> Your 'Put' Histogram threshold is too high, or RSI is never < 45.")

if __name__ == "__main__":
    calibrate()