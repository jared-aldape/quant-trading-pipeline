import sys
import duckdb
import pandas as pd
import pandas_ta as ta
import numpy as np
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("Optimizer")

# ==============================================================================
# 2. CONFIGURATION SPACE
# ==============================================================================
# We scan the "Oversold" zone (20-44) to find the mean-reversion edge.
RSI_RANGES = range(20, 46, 2) 
LOOK_FORWARD_DAYS = 5           # Swing Trade Horizon
MIN_ROI_TARGET = 0.0            # Breakeven+

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def fetch_data():
    """Fetch Index Data from The Vault (Naive UTC)"""
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # Fetch SPX (Price)
    df_spx = con.execute(f"""
        SELECT datetime_utc, close as spx_close 
        FROM {config.TBL_INDICES} WHERE ticker='SPX' ORDER BY datetime_utc ASC
    """).df()
    
    # Fetch VIX (Signal)
    df_vix = con.execute(f"""
        SELECT datetime_utc, close as vix_close 
        FROM {config.TBL_INDICES} WHERE ticker='VIX' ORDER BY datetime_utc ASC
    """).df()
    
    con.close()
    
    # Merge on Time (AsOf merge to align timestamps)
    df = pd.merge_asof(
        df_vix.sort_values('datetime_utc'),
        df_spx.sort_values('datetime_utc'),
        on='datetime_utc',
        direction='backward'
    )
    return df

def calculate_indicators(df):
    """Apply Technical Indicators"""
    # VIX RSI (14)
    df['vix_rsi'] = ta.rsi(df['vix_close'], length=14)
    
    # VIX MACD (12, 26, 9)
    macd = ta.macd(df['vix_close'])
    df['vix_macd'] = macd['MACD_12_26_9']
    df['vix_macd_hist'] = macd['MACDh_12_26_9']
    
    return df

def run_optimization():
    log.info(f"🧪 Starting Grid Search (Forward Look: {LOOK_FORWARD_DAYS} days)...")
    
    # 1. Get Data & Resample to Daily
    df_raw = fetch_data()
    df_raw['date'] = df_raw['datetime_utc'].dt.date
    # Group by date to get EOD values for standard backtesting
    df = df_raw.groupby('date').last().reset_index() 
    
    df = calculate_indicators(df)
    
    # Calculate Forward Return (The "Crystal Ball")
    # shift(-N) moves future price N days BACK to the current row
    df['spx_future'] = df['spx_close'].shift(-LOOK_FORWARD_DAYS)
    df['trade_return'] = (df['spx_future'] - df['spx_close']) / df['spx_close']
    
    results = []
    
    # 2. The Loop (Grid Search)
    for rsi_thresh in RSI_RANGES:
        for use_macd in [True, False]:
            # Apply Filter
            if use_macd:
                # RSI + Momentum Confirmation
                signals = df[(df['vix_rsi'] < rsi_thresh) & (df['vix_macd_hist'] < 0)]
                strategy_name = f"RSI < {rsi_thresh} + MACD"
            else:
                # Pure RSI (Mean Reversion)
                signals = df[df['vix_rsi'] < rsi_thresh]
                strategy_name = f"RSI < {rsi_thresh} (Pure)"
            
            if signals.empty:
                continue
                
            # 3. Measure Performance
            win_count = len(signals[signals['trade_return'] > MIN_ROI_TARGET])
            total_trades = len(signals)
            win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
            avg_return = signals['trade_return'].mean() * 100
            
            results.append({
                "Strategy": strategy_name,
                "RSI_Thresh": rsi_thresh,
                "Use_MACD": use_macd,
                "Trades": total_trades,
                "Win_Rate": win_rate,
                "Avg_Return_5d": avg_return
            })
            
    # 4. Report
    res_df = pd.DataFrame(results).sort_values("Avg_Return_5d", ascending=False)
    
    # Formatting for Display
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 1000)
    pd.set_option('display.float_format', '{:.2f}'.format)
    
    print("\n" + "="*80)
    print(f"🏆 OPTIMIZATION LEADERBOARD (Top 20 Configs)")
    print("="*80)
    print(res_df.head(20).to_string(index=False))
    print("="*80)
    
    # Save to CSV
    output_path = config.REPORTS_DIR / "optimization_results.csv"
    res_df.to_csv(output_path, index=False)
    log.info(f"✅ Report saved to: {output_path}")

if __name__ == "__main__":
    run_optimization()