import sys
import duckdb
import pandas as pd
import numpy as np
import pandas_ta as ta
import itertools
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# Setup Root Directory for imports
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config
from src.core import engine_ml_precision

def run_grid_search(days_back=30):
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. DEFINE THE WINDOW
    end_dt = datetime.now(pytz.UTC)
    start_dt = end_dt - timedelta(days=days_back)
    
    print(f"📡 PRE-LOADING VAULT DATA FOR BRUTE-FORCE OPTIMIZATION...")
    print(f"   Window: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}")
    
    # 2. LOAD MARKET CONTEXT (VIX/XSP)
    lookback_start = start_dt - timedelta(days=2)
    df_mkt = con.execute(f"SELECT * FROM indices_1m WHERE datetime_utc >= '{lookback_start}'").df()
    
    vix = df_mkt[df_mkt['ticker'] == 'VIX'].copy()
    vix[['macd','signal','hist']] = ta.macd(vix['close'])
    vix['rsi'] = ta.rsi(vix['close'])
    vix['v_diff'] = vix['macd'] - vix['signal']
    vix['cross'] = np.where((vix['v_diff'] > 0) & (vix['v_diff'].shift(1) <= 0), 1, 0)
    
    xsp = df_mkt[df_mkt['ticker'] == 'XSP'].copy()
    xsp[['macd','signal','hist']] = ta.macd(xsp['close'])
    x_adx = ta.adx(xsp['high'], xsp['low'], xsp['close'])
    xsp['adx'] = x_adx['ADX_14'] if x_adx is not None else 20
    xsp['x_diff'] = xsp['macd'] - xsp['signal']
    xsp['cross'] = np.where((xsp['x_diff'] > 0) & (xsp['x_diff'].shift(1) <= 0), 1, 0)

    # 3. LOAD SIGNALS (With Chronological Fix)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    sig_query = f"""
        SELECT * FROM trade_manifest 
        WHERE entry_timestamp_utc >= {start_ms} 
        AND entry_timestamp_utc <= {end_ms} 
        ORDER BY entry_timestamp_utc ASC
    """
    signals = con.execute(sig_query).df()
    
    if signals.empty:
        print("❌ No signals found to optimize.")
        return
        
    signals['entry_timestamp_utc'] = pd.to_datetime(signals['entry_timestamp_utc'], unit='ms').dt.tz_localize('UTC')
    print(f"✅ Loaded {len(signals)} sequential signals. Pre-calculating ML confidence...")
    
    # 4. PRE-CALCULATE CONFIDENCE & OPTION TRACKS (Performance Boost)
    enriched_signals = []
    for row in signals.itertuples():
        t_utc = row.entry_timestamp_utc.replace(tzinfo=None)
        v_ctx = vix[vix['datetime_utc'] <= t_utc].tail(1)
        x_ctx = xsp[xsp['datetime_utc'] <= t_utc].tail(1)
        if v_ctx.empty or x_ctx.empty: continue
        
        # Get AI Confidence
        conf = engine_ml_precision.predict_success(
            row.trade_type, vix_val=v_ctx['rsi'].iloc[0], vix_hist=v_ctx['hist'].iloc[0], 
            vix_cross=v_ctx['cross'].iloc[0], xsp_hist=x_ctx['hist'].iloc[0], 
            xsp_cross=x_ctx['cross'].iloc[0], adx=x_ctx['adx'].iloc[0], trade_hour=row.entry_timestamp_utc.hour
        )
        
        # Pre-fetch Tier-3 Options chain data
        is_call = 'CALL' in row.trade_type
        op_type = 'C' if is_call else 'P'
        q_opt = f"SELECT ticker, close FROM options_1m WHERE datetime_utc = '{row.entry_timestamp_utc}' AND SUBSTRING(ticker, 10, 1) = '{op_type}' "
        q_opt += f"AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 {' > ' if is_call else ' < '} {row.xsp_price} ORDER BY ticker {'ASC' if is_call else 'DESC'} LIMIT 1 OFFSET 2"
        opt_df = con.execute(q_opt).df()
        
        if not opt_df.empty:
            ticker = opt_df.iloc[0]['ticker']
            entry_px = opt_df.iloc[0]['close']
            track = con.execute(f"SELECT high, low, close FROM options_1m WHERE ticker='{ticker}' AND datetime_utc > '{row.entry_timestamp_utc}' LIMIT 240").df()
            if not track.empty:
                enriched_signals.append({
                    'time': row.entry_timestamp_utc,
                    'type': row.trade_type,
                    'conf': conf,
                    'entry_px': entry_px,
                    'track': track
                })
    con.close()

    # ==========================================================
    # 5. DEFINE THE HYPERPARAMETER MATRIX
    # ==========================================================
    conf_thresholds = [60.0, 65.0, 70.0, 75.0]  # How strict should the Oracle be?
    cooldowns_mins  = [15, 30]                  # How long to wait after firing?
    take_profits    = [1.30, 1.45, 1.60]        # +30%, +45%, +60% target
    stop_losses     = [0.70, 0.50]              # -30%, -50% stop loss
    
    combinations = list(itertools.product(conf_thresholds, cooldowns_mins, take_profits, stop_losses))
    print(f"\n🚀 IGNITING GRID SEARCH: Simulating {len(combinations)} unique configurations...")

    results = []
    
    # 6. EXECUTE THE SIMULATIONS
    for conf_t, cool_t, tp_mult, sl_mult in combinations:
        capital = 1000.0
        last_time = None
        wins, total = 0, 0
        
        for sig in enriched_signals:
            if sig['conf'] < conf_t: 
                continue
                
            if last_time and (sig['time'] - last_time) < timedelta(minutes=cool_t): 
                continue
            
            target = sig['entry_px'] * tp_mult
            stop = sig['entry_px'] * sl_mult
            
            status = 'LOSS'
            exit_px = sig['track'].iloc[-1]['close'] # Default to track end
            
            for t in sig['track'].itertuples():
                if t.low <= stop: 
                    exit_px = stop
                    break
                if t.high >= target: 
                    status = 'WIN'
                    exit_px = target
                    break
                
            if status == 'WIN': wins += 1
            total += 1
            last_time = sig['time']
            
            # Allocation math (capping at 5% per trade for risk management)
            trade_capital = capital * 0.05
            net_return = (exit_px - sig['entry_px']) / sig['entry_px']
            net_pnl = (trade_capital * net_return) * 0.985 # 1.5% Slippage Tax
            capital += net_pnl

        if total > 0:
            win_rate = (wins/total)*100
            # Only record strategies that don't blow up the account
            if capital > 0:
                results.append({
                    'Conf >= %': conf_t,
                    'Cooldown': f"{cool_t}m",
                    'Target': f"+{(tp_mult-1)*100:.0f}%",
                    'Stop': f"-{(1-sl_mult)*100:.0f}%",
                    'Trades': total,
                    'Win Rate': f"{win_rate:.1f}%",
                    'End Cap': capital,
                    'Return': f"{((capital-1000)/1000)*100:.1f}%"
                })

    # 7. RANK AND OUTPUT THE RESULTS
    if not results:
        print("⚠️ No profitable configurations found.")
        return

    res_df = pd.DataFrame(results)
    best_df = res_df.sort_values('End Cap', ascending=False).head(5)
    
    print("\n" + "="*85)
    print("👑 THE APEX CONFIGURATIONS (TOP 5 HIGHEST YIELD)")
    print("="*85)
    # Format End Cap as currency
    best_df['End Cap'] = best_df['End Cap'].apply(lambda x: f"${x:.2f}")
    print(best_df.to_string(index=False))
    print("="*85)

if __name__ == "__main__":
    run_grid_search(days_back=30)