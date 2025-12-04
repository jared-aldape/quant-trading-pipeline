import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path

# ==============================================================================
# PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("EV_Analyzer")

class ExpectedValueEngine:
    def __init__(self):
        self.db_path = str(config.DB_FILE)

    def fetch_recent_performance(self, limit=50):
        """Fetches the last N trades from the simulation log."""
        try:
            con = duckdb.connect(self.db_path, read_only=True)
            
            # Verify table exists
            tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
            if config.TBL_SIM_LOG not in tables:
                return pd.DataFrame()

            query = f"""
                SELECT return_pct, pnl, entry_time 
                FROM {config.TBL_SIM_LOG} 
                ORDER BY entry_time DESC 
                LIMIT {limit}
            """
            df = con.execute(query).df()
            con.close()
            return df
        except Exception as e:
            log.error(f"EV Fetch Error: {e}")
            return pd.DataFrame()

    def calculate_kelly(self, win_rate, win_loss_ratio):
        """
        Calculates Kelly Criterion.
        f* = (bp - q) / b
        b = odds received (win/loss ratio)
        p = probability of winning
        q = probability of losing (1-p)
        """
        if win_loss_ratio <= 0: return 0.0
        return (win_loss_ratio * win_rate - (1 - win_rate)) / win_loss_ratio

    def generate_risk_card(self):
        """Generates the Daily Risk Card metrics."""
        df = self.fetch_recent_performance(limit=30)
        
        if df.empty:
            return {
                "status": "WAITING",
                "ev_per_trade": 0.0,
                "kelly_pct": 0.0,
                "rec_stop": 0.15, # Default Safety
                "rec_target": 0.30
            }

        # 1. Basic Metrics
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]
        
        win_count = len(wins)
        total_count = len(df)
        win_rate = win_count / total_count if total_count > 0 else 0
        
        avg_win = wins['return_pct'].mean() if not wins.empty else 0
        avg_loss = abs(losses['return_pct'].mean()) if not losses.empty else 0
        
        # 2. Expected Value (EV)
        # EV = (Win% * AvgWin) - (Loss% * AvgLoss)
        ev_score = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        # 3. Kelly Criterion (Optimal Sizing)
        win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0
        kelly_raw = self.calculate_kelly(win_rate, win_loss_ratio)
        kelly_conservative = max(0.0, kelly_raw * 0.5) # Half-Kelly for safety

        # 4. Dynamic Stop/Target Suggestion (Based on Volatility)
        # We look at the standard deviation of returns
        volatility = df['return_pct'].std()
        
        # If volatility is high, widen stops. If low, tighten them.
        # Base assumptions: Stop = 1x Vol, Target = 2x Vol + EV Bias
        rec_stop = max(10.0, volatility * 1.5) # Floor at 10%
        rec_target = max(20.0, rec_stop * 2.0) # Target 2R minimum

        return {
            "status": "ACTIVE",
            "sample_size": total_count,
            "win_rate": round(win_rate * 100, 1),
            "ev_per_trade": round(ev_score, 2),
            "kelly_full": round(kelly_raw * 100, 1),
            "kelly_safe": round(kelly_conservative * 100, 1),
            "rec_stop": round(rec_stop / 100, 2),   # Format for execution (0.15)
            "rec_target": round(rec_target / 100, 2) # Format for execution (0.30)
        }

if __name__ == "__main__":
    engine = ExpectedValueEngine()
    card = engine.generate_risk_card()
    print("\n--- DAILY RISK CARD ---")
    print(f"STATUS:      {card['status']}")
    print(f"WIN RATE:    {card.get('win_rate', 0)}%")
    print(f"EV (Exp):    {card.get('ev_per_trade', 0)}%")
    print(f"KELLY (Safe): {card.get('kelly_safe', 0)}% Allocation")
    print(f"SUGGESTED STOP:   {card.get('rec_stop', 0)*100}%")
    print(f"SUGGESTED TARGET: {card.get('rec_target', 0)*100}%")