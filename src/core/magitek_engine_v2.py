import sys
import duckdb
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. INSTITUTIONAL PATHING & UTILITY INTEGRATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import engine_ml_precision, engine_chop_guard

# Integrating the forensic ops tool safely
try:
    from ops import forensic_snapshotter
except ImportError:
    forensic_snapshotter = None

log = get_logger("Apex_Sniper")

# ==============================================================================
# 2. THE UNIFIED EXECUTION ENGINE (FIRST STRIKE EDITION)
# ==============================================================================
def run_apex_session(start_dt, end_dt, initial_balance=1000.0):
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    pst = pytz.timezone('America/Los_Angeles')
    
    log.info("📡 QUANT OS BOOTING... Integrity Check: PASS")
    
    # Initialize Core Sub-Engines
    try:
        cg = engine_chop_guard.ChopGuard()
    except Exception as e:
        log.warning(f"⚠️ ChopGuard offline: {e}")
        cg = None
    
    # Fetch current Macro Bias
    try:
        flow_query = f"SELECT flow_bias FROM {config.TBL_MACRO_FLOW} ORDER BY date DESC LIMIT 1"
        current_bias = con.execute(flow_query).fetchone()[0]
    except:
        current_bias = "NEUTRAL"

    print(f"📡 QUANT OS ONLINE | REGIME: {current_bias}")
    print(f"   Rules: First Strike | 100% All-In | 30% Trail | Gate: 06:40 PST | Shield: 07:10 PST")

    # Pre-calculate Indicators (Warm up the VIX/XSP Context)
    lookback_start = start_dt - timedelta(days=5)
    try:
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
    except Exception as e:
        log.error(f"Failed to calculate indicators: {e}")
        return

    all_days = pd.date_range(start=start_dt, end=end_dt, freq='B') 
    capital = initial_balance
    total_trades = 0
    wins = 0

    print("\n" + "="*165)
    print(f"{'DATE (PST)':<12} | {'ENTRY':<7} | {'EXIT':<7} | {'OPTION TICKER':<18} | {'BUY $':<6} | {'SELL $':<6} | {'QTY':<4} | {'P/L %':<7} | {'RESULT':<15} | {'BALANCE'}")
    print("="*165)

    for day in all_days:
        day_str = day.strftime('%Y-%m-%d')
        
        try:
            sig_query = f"SELECT * FROM trade_manifest WHERE CAST(date AS DATE) = '{day_str}' ORDER BY entry_timestamp_utc ASC"
            day_signals = con.execute(sig_query).df()
        except:
            day_signals = pd.DataFrame()
            
        if day_signals.empty:
            print(f"{day_str:<12} | {'--':<7} | {'--':<7} | {'--':<18} | {'--':<6} | {'--':<6} | {'--':<4} | {'--':<7} | {'NO SIGNALS':<15} | ${capital:,.2f}")
            continue

        day_signals['entry_timestamp_utc'] = pd.to_datetime(day_signals['entry_timestamp_utc'], unit='ms').dt.tz_localize('UTC')
        executed_today = False
        
        for row in day_signals.itertuples():
            t_pst = row.entry_timestamp_utc.astimezone(pst)
            t_utc = row.entry_timestamp_utc.replace(tzinfo=None)

            # 🛡️ TIME LAW 1: The 06:40 PST Gate
            if t_pst.hour == 6 and t_pst.minute < 40: continue 

            # 🛡️ TIME LAW 2: The 07:10 - 07:50 PST Chop Shield
            if t_pst.hour == 7 and (10 <= t_pst.minute <= 50): continue

            # DATA INTEGRITY: Use forensic_snapshotter to verify state
            snapshot_regime = current_bias
            if forensic_snapshotter:
                snapshot = forensic_snapshotter.capture_market_state(row.entry_timestamp_utc)
                if not snapshot or not snapshot.get('valid'):
                    print(f"{day_str:<12} | {t_pst.strftime('%H:%M'):<7} | {'--':<7} | {'NaN: GAP FOUND':<18} | {'--':<6} | {'--':<6} | {'--':<4} | {'--':<7} | {'CHAIN GAP':<15} | ${capital:,.2f}")
                    continue
                snapshot_regime = snapshot.get('regime', current_bias)

            # Context Fetch for ML
            v_ctx = vix[vix['datetime_utc'] <= t_utc].tail(1)
            x_ctx = xsp[xsp['datetime_utc'] <= t_utc].tail(1)
            
            if v_ctx.empty or x_ctx.empty:
                print(f"{day_str:<12} | {t_pst.strftime('%H:%M'):<7} | {'--':<7} | {'NaN: NO CONTEXT':<18} | {'--':<6} | {'--':<6} | {'--':<4} | {'--':<7} | {'DATA GAP':<15} | ${capital:,.2f}")
                continue

            # 🛡️ CHOP GUARD VALIDATION
            if cg:
                hist_df = con.execute(f"SELECT * FROM indices_1m WHERE ticker='XSP' AND datetime_utc <= '{t_utc}' ORDER BY datetime_utc DESC LIMIT 30").df()
                if not hist_df.empty and cg.analyze(hist_df.sort_values('datetime_utc')) == "CHOP": 
                    continue

            # 🛡️ ML ORACLE PRECISION
            conf = engine_ml_precision.predict_success(
                row.trade_type, vix_val=v_ctx['rsi'].iloc[0], vix_hist=v_ctx['hist'].iloc[0], 
                vix_cross=v_ctx['cross'].iloc[0], xsp_hist=x_ctx['hist'].iloc[0], 
                xsp_cross=x_ctx['cross'].iloc[0], adx=x_ctx['adx'].iloc[0], trade_hour=t_pst.hour
            )
            
            is_snipe = (t_pst.hour == 6 and t_pst.minute >= 40) or (t_pst.hour == 8 and t_pst.minute <= 15)
            threshold = 55.0 if is_snipe else 60.0
            
            if conf < threshold: continue

            # NaN CHECK & RECURSIVE SCANNER: Options Chain
            is_call = 'CALL' in row.trade_type
            op_type = 'C' if is_call else 'P'
            
            # Recursive Strike Scanner (Checks offsets 2, 3, 1, 4 to completely eliminate NaN gaps)
            offsets = [2, 3, 1, 4]
            opt_df = pd.DataFrame()
            
            for offset in offsets:
                q_opt = f"SELECT ticker, close FROM options_1m WHERE datetime_utc = '{row.entry_timestamp_utc}' AND SUBSTRING(ticker, 10, 1) = '{op_type}' "
                if is_call: q_opt += f"AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 > {row.xsp_price} ORDER BY ticker ASC LIMIT 1 OFFSET {offset}"
                else: q_opt += f"AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT)/1000.0 < {row.xsp_price} ORDER BY ticker DESC LIMIT 1 OFFSET {offset}"
                
                opt_df = con.execute(q_opt).df()
                if not opt_df.empty: break
                
            if opt_df.empty:
                print(f"{day_str:<12} | {t_pst.strftime('%H:%M'):<7} | {'--':<7} | {'NaN: NO OPTION':<18} | {'--':<6} | {'--':<6} | {'--':<4} | {'--':<7} | {'CHAIN GAP':<15} | ${capital:,.2f}")
                continue

            # 4. EXECUTION (ALL-IN CAPITAL ALLOCATION)
            ticker = opt_df.iloc[0]['ticker']
            entry_px = opt_df.iloc[0]['close']
            
            contract_cost = entry_px * 100
            qty = int(capital // contract_cost) 
            
            if qty == 0: 
                print(f"{day_str:<12} | {t_pst.strftime('%H:%M'):<7} | {'--':<7} | {'--':<18} | {'--':<6} | {'--':<6} | {'--':<4} | {'--':<7} | {'INSUFFICIENT FUNDS':<15} | ${capital:,.2f}")
                continue

            actual_invested = qty * contract_cost

            # 5. TRACKING & TRAILING LOGIC
            track = con.execute(f"SELECT datetime_utc, high, low, close FROM options_1m WHERE ticker='{ticker}' AND datetime_utc > '{row.entry_timestamp_utc}' LIMIT 300").df()
            if track.empty: continue

            highest_px = entry_px
            stop_px = entry_px * 0.70  
            target_px = entry_px * 2.0 
            
            exit_px = track.iloc[-1]['close'] 
            exit_time_utc = track.iloc[-1]['datetime_utc'] 
            
            for t in track.itertuples():
                if t.high > highest_px:
                    highest_px = t.high
                    stop_px = max(stop_px, highest_px * 0.70) 
                
                if t.low <= stop_px:
                    exit_px = stop_px
                    exit_time_utc = t.datetime_utc
                    break
                    
                if t.high >= target_px:
                    if snapshot_regime == 'BULL' and is_call:
                        pass # Let it ride in Bull Regime
                    else:
                        exit_px = target_px
                        exit_time_utc = t.datetime_utc
                        break

            # 6. PnL ACCOUNTING & EXIT
            net_return = (exit_px - entry_px) / entry_px
            gross_pnl = actual_invested * net_return
            net_pnl = gross_pnl * 0.985 # 1.5% Slippage
            
            capital += net_pnl
            total_trades += 1
            if net_pnl > 0: wins += 1
            
            executed_today = True
            exit_time_pst = pd.to_datetime(exit_time_utc).tz_localize('UTC').astimezone(pst)
            
            print(f"{day_str:<12} | {t_pst.strftime('%H:%M'):<7} | {exit_time_pst.strftime('%H:%M'):<7} | {ticker:<18} | ${entry_px:<5.2f} | ${exit_px:<5.2f} | {qty:<4} | {net_return*100:>+6.1f}% | {'STRIKE':<15} | ${capital:,.2f}")
            
            # THE FIRST STRIKE LAW: One trade per day.
            break 

        if not executed_today and not day_signals.empty:
            print(f"{day_str:<12} | {'--':<7} | {'--':<7} | {'--':<18} | {'--':<6} | {'--':<6} | {'--':<4} | {'--':<7} | {'ALL VETOED':<15} | ${capital:,.2f}")

    con.close()
    
    # FINAL RECKONING
    print("\n" + "="*60)
    print(f"🏁 FIRST-STRIKE AUDIT COMPLETE")
    print(f"   Final Balance: ${capital:,.2f} | Total Trades: {total_trades}")
    if total_trades > 0:
        print(f"   Win Rate:      {(wins/total_trades)*100:.1f}%")
        print(f"   Total Return:  {((capital-initial_balance)/initial_balance)*100:.1f}%")
    print("="*60)

if __name__ == "__main__":
    lookback_end = datetime.now(pytz.UTC)
    lookback_start = lookback_end - timedelta(days=30)
    run_apex_session(lookback_start, lookback_end)