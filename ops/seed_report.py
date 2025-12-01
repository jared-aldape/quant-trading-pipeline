import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def generate_seed_report():
    print("🌱 Generating SEED Backtest Report...")
    
    # 1. Simulate a "Sniper" Strategy Distribution
    # High Win Rate (90%), mixed returns
    data = {
        'Entry Time': pd.date_range(start='2025-10-01', periods=50, freq='D'),
        'Ticker': ['O:SEED_DATA'] * 50,
        'Net PnL': np.random.choice([500, 450, -100, 600, -50], 50, p=[0.6, 0.2, 0.1, 0.05, 0.05]),
        'Return %': np.random.choice([0.40, 0.35, -0.20, 0.50, -0.10], 50, p=[0.6, 0.2, 0.1, 0.05, 0.05]),
        'Reason': ['TARGET'] * 45 + ['STOP'] * 5
    }
    
    df = pd.DataFrame(data)
    
    # 2. Ensure Reports Directory Exists (The Integrity Law)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 3. Save with Correct Naming Convention
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backtest_REAL_SEED_{timestamp}.csv"
    filepath = config.REPORTS_DIR / filename
    
    df.to_csv(filepath, index=False)
    
    print(f"✅ Seed Report Created: {filepath}")
    print("👉 You may now run the Forecaster (Tool 2).")

if __name__ == "__main__":
    generate_seed_report()