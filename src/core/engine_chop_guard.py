import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

log = get_logger("ChopGuard")

class ChopGuard:
    def __init__(self):
        self.adx_period = 14
        self.bb_period = 20
        self.bb_std = 2

    def calculate_adx(self, df):
        """Calculates ADX to measure trend STRENGTH (not direction)."""
        if len(df) < self.adx_period + 1: return 0
        
        # True Range Calculation
        df = df.copy()
        df['tr0'] = abs(df['high'] - df['low'])
        df['tr1'] = abs(df['high'] - df['close'].shift(1))
        df['tr2'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
        
        # Directional Movement
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
        
        # Smoothing (Wilder's)
        tr_smooth = df['tr'].ewm(alpha=1/self.adx_period, adjust=False).mean()
        plus_di = 100 * (df['plus_dm'].ewm(alpha=1/self.adx_period, adjust=False).mean() / tr_smooth)
        minus_di = 100 * (df['minus_dm'].ewm(alpha=1/self.adx_period, adjust=False).mean() / tr_smooth)
        
        # ADX Calculation
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(alpha=1/self.adx_period, adjust=False).mean()
        
        return adx.iloc[-1]

    def analyze(self, df):
        """
        Returns market state: 'TRENDING', 'CHOP', or 'CRITICAL_SQUEEZE'
        """
        if df.empty or len(df) < 20: return "UNKNOWN"
        
        # 1. Bollinger Band Squeeze (The 'Waiting for News' detector)
        close = df['close']
        sma = close.rolling(self.bb_period).mean().iloc[-1]
        std = close.rolling(self.bb_period).std().iloc[-1]
        
        if std == 0: return "UNKNOWN"
        
        upper = sma + (self.bb_std * std)
        lower = sma - (self.bb_std * std)
        
        # Bandwidth %
        bandwidth = (upper - lower) / sma
        
        # 2. ADX (Trend Strength)
        adx = self.calculate_adx(df)
        
        # LOGIC GATES
        # CRITICAL SQUEEZE: Volatility is dead. Massive move imminent. DO NOT HOLD.
        if bandwidth < 0.0015: 
            return "CRITICAL_SQUEEZE" 
            
        # CHOP: Trend is dead. Price is drifting. Theta will kill you.
        if adx < 20:
            return "CHOP" 
            
        return "TRENDING" # Green Light

# Singleton Export
chop_engine = ChopGuard()