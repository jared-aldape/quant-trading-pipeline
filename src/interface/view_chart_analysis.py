import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import duckdb
from datetime import datetime, time, timedelta
import pytz
import pathlib
import sys
import numpy as np

# ==============================================================================
# 1. PATH & CONFIG SETUP
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ==============================================================================
# 2. HELPER: WALL CLOCK TIME (UTC -> Local Naive)
# ==============================================================================
def to_wall_clock(series):
    if series.empty: return series
    if series.dt.tz is None:
        series = series.dt.tz_localize('UTC')
    else:
        series = series.dt.tz_convert('UTC')
    series = series.dt.tz_convert(config.TZ_LOCAL)
    return series.dt.tz_localize(None)

# ==============================================================================
# 3. DATA INGESTION
# ==============================================================================
def fetch_unique_dates(trade_type_filter='call'):
    try:
        if not config.DB_FILE.exists(): return []
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_MANIFEST not in tables: 
             con.close(); return []

        t_filter = trade_type_filter.upper()
        query = f"""
            SELECT date, COUNT(*) as sig_count
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{t_filter}'
            GROUP BY date
            ORDER BY date DESC
        """
        df = con.execute(query).df()
        con.close()
        
        if df.empty: return []
        options = []
        for _, row in df.iterrows():
            d_str = row['date'].strftime('%Y-%m-%d') if not isinstance(row['date'], str) else row['date']
            label = f"{d_str} ({row['sig_count']} Signals)"
            options.append({'label': label, 'value': d_str})
        return options
    except Exception as e: 
        print(f"Date Fetch Error: {e}")
        return []

def scout_day_performance(date_str, trade_type_filter='call'):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        t_type = trade_type_filter.upper()
        
        query = f"""
            SELECT entry_timestamp_utc, signal_type, xsp_price, meta_data 
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{t_type}' 
            AND date = '{date_str}'
            ORDER BY entry_timestamp_utc ASC
        """
        signals = con.execute(query).df()
        
        if signals.empty: 
            con.close(); return [], None

        options_list = []
        best_ts = None
        max_gain_overall = -999.0

        for i, row in signals.iterrows():
            ts = row['entry_timestamp_utc']
            entry_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
            date_fmt = entry_dt.strftime('%y%m%d')
            opt_code = 'C' if t_type == 'CALL' else 'P'
            strike = int(round(float(row['xsp_price'])) * 1000)
            ticker = f"O:XSP{date_fmt}{opt_code}{strike:08d}"
            
            day_date = entry_dt.date()
            start_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            end_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            
            tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
            if config.TBL_OPTIONS in tables:
                pq = f"SELECT datetime_utc, open FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
                prices = con.execute(pq).df()
            else:
                prices = pd.DataFrame()

            gain_str, gain_val = "N/A", -100.0
            
            if not prices.empty:
                signal_ts_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).replace(tzinfo=None)
                try:
                    prices['datetime_utc'] = pd.to_datetime(prices['datetime_utc'])
                    if prices['datetime_utc'].dt.tz is not None:
                         prices['datetime_utc'] = prices['datetime_utc'].dt.tz_localize(None)

                    idx = prices['datetime_utc'].sub(signal_ts_dt).abs().idxmin()
                    entry_px = prices.loc[idx, 'open']
                    prices_after_entry = prices.loc[idx:]
                    max_px = prices_after_entry['open'].max() if not prices_after_entry.empty else entry_px
                    
                    if entry_px > 0.05:
                        gain_val = ((max_px - entry_px) / entry_px) * 100
                        gain_str = f"+{gain_val:.1f}%"
                    else:
                        gain_str = "Noise (<$0.05)"
                        gain_val = 0
                except:
                    gain_str = "Err"
            
            if gain_val > max_gain_overall:
                max_gain_overall = gain_val
                best_ts = ts

            time_str = entry_dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
            clean_meta = str(row['meta_data']).replace('VIX_FRACTAL_LONG', '').replace('VIX_FRACTAL_SHORT', '').strip()
            if "|" in clean_meta: clean_meta = clean_meta.split('|')[-1].strip()
            
            label = f"Signal #{i+1} ({time_str}) | Gain: {gain_str} | {clean_meta}"
            options_list.append({'label': label, 'value': ts})

        con.close()
        if not best_ts and options_list: best_ts = options_list[0]['value']
        return options_list, best_ts
    except Exception as e:
        print(f"Scout Error: {e}")
        return [], None

def fetch_trade_performance(entry_ts_ms, trade_type, xsp_price, sim_stop_pct=20):
    """
    Enhanced: Returns DF with 'pnl_pct' AND 'sim_pnl_pct' (simulated stop).
    """
    try:
        date_obj = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        date_str = date_obj.strftime('%y%m%d')
        opt_type = 'C' if trade_type.upper() == 'CALL' else 'P'
        strike_raw = round(float(xsp_price))
        strike_str = f"{int(strike_raw * 1000):08d}"
        ticker = f"O:XSP{date_str}{opt_type}{strike_str}"

        day_date = date_obj.date()
        start_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        end_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_OPTIONS not in tables:
             con.close(); return None, ticker

        query = f"SELECT datetime_utc, open FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
        df = con.execute(query).df()
        con.close()

        if df.empty: return None, ticker

        entry_dt_utc = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).replace(tzinfo=None)
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
        try:
            if df['datetime_utc'].dt.tz is not None:
                 df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(None)
            idx = df['datetime_utc'].sub(entry_dt_utc).abs().idxmin()
            # Trim to start from entry
            df = df.loc[idx:].copy()
            entry_price = df.iloc[0]['open']
        except:
            entry_price = df.iloc[0]['open']

        df['pnl_dollars_raw'] = (df['open'] - entry_price) * 100
        entry_price_safe = entry_price if entry_price > 0.05 else 9999.9 
        df['pnl_pct'] = ((df['open'] - entry_price) / entry_price_safe) * 100
        
        # --- WHAT IF SIMULATOR ---
        # Logic: Trailing Stop. 
        # 1. Track Max Price since entry. 
        # 2. If Price < Max * (1 - stop), exit.
        
        stop_mult = 1.0 - (sim_stop_pct / 100.0)
        df['rolling_max'] = df['open'].cummax()
        df['stop_level'] = df['rolling_max'] * stop_mult
        
        # Identify stop hit
        stop_hits = df[df['open'] < df['stop_level']]
        
        df['sim_pnl_pct'] = df['pnl_pct'] # Default to hold
        if not stop_hits.empty:
            first_stop_idx = stop_hits.index[0]
            # After stop hit, flatline the P&L (cash)
            exit_pnl = df.loc[first_stop_idx, 'pnl_pct']
            df.loc[first_stop_idx:, 'sim_pnl_pct'] = exit_pnl
            
        df['datetime_local'] = to_wall_clock(df['datetime_utc'])
        return df, ticker
    except Exception as e: 
        print(f"Trade Perf Error: {e}")
        return None, "ERROR"

def fetch_executions(entry_ts_ms, root):
    """
    Forensics: Find actual fills in active_rh_log close to signal.
    """
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if 'active_rh_log' not in tables:
             con.close(); return pd.DataFrame()
             
        # Look for fills +/- 5 mins of signal
        sig_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc)
        s_start = (sig_dt - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
        s_end = (sig_dt + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S') # Allow wide window for fills
        
        # We search by ROOT (e.g. XSP) since we don't know the exact option symbol in the log sometimes
        q = f"""
            SELECT entry_time_utc, avg_price, action, status 
            FROM active_rh_log 
            WHERE status = 'FILLED' 
            AND root = '{root}'
            AND entry_time_utc >= '{s_start}' 
            AND entry_time_utc <= '{s_end}'
        """
        fills = con.execute(q).df()
        con.close()
        
        if not fills.empty:
             fills['datetime_utc'] = pd.to_datetime(fills['entry_time_utc'])
             fills['datetime_local'] = to_wall_clock(fills['datetime_utc'])
             
        return fills
    except:
        return pd.DataFrame()

def fetch_indicators(entry_ts_ms):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        entry_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        day_date = entry_dt.date()
        s_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        e_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_INDICES not in tables:
             con.close(); return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        df_idx = con.execute(f"SELECT datetime_utc, ticker, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker IN ('VIX', 'XSP') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        
        tbl_fut = getattr(config, 'TBL_FUTURES', 'futures_1m')
        if tbl_fut in tables:
             try: df_fut = con.execute(f"SELECT datetime_utc, ticker, close FROM {tbl_fut} WHERE ticker = 'ES' AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
             except: df_fut = pd.DataFrame()
        else:
             df_fut = pd.DataFrame()
        con.close()
        
        xsp = pd.DataFrame()
        vix = pd.DataFrame()
        es = pd.DataFrame()
        
        if not df_idx.empty:
            df_idx['datetime_utc'] = pd.to_datetime(df_idx['datetime_utc'])
            df_idx['datetime_local'] = to_wall_clock(df_idx['datetime_utc'])
            
            if 'XSP' in df_idx['ticker'].values:
                xsp = df_idx[df_idx['ticker'] == 'XSP'].copy().set_index('datetime_local')
                xsp['sma_50'] = xsp['close'].rolling(50).mean() # X-RAY: Added SMA

            if 'VIX' in df_idx['ticker'].values:
                vix = df_idx[df_idx['ticker'] == 'VIX'].copy().set_index('datetime_local')
                vix['ema12'] = vix['close'].ewm(span=12).mean()
                vix['ema26'] = vix['close'].ewm(span=26).mean()
                vix['macd'] = vix['ema12'] - vix['ema26']
                vix['signal'] = vix['macd'].ewm(span=9).mean()
                vix['hist'] = vix['macd'] - vix['signal']
                delta = vix['close'].diff()
                up = delta.clip(lower=0)
                down = -1 * delta.clip(upper=0)
                rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
                vix['rsi'] = 100 - (100 / (1 + rs))

        if not df_fut.empty:
            df_fut['datetime_utc'] = pd.to_datetime(df_fut['datetime_utc'])
            df_fut['datetime_local'] = to_wall_clock(df_fut['datetime_utc'])
            df_fut['scaled_close'] = df_fut['close'] / 10.0 
            es = df_fut.set_index('datetime_local')

        return xsp, vix, es
    except Exception as e: 
        print(f"Indicator Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("LIBRA SCAN COMMAND", className="magitek-h2"),
                html.P("FORENSIC CHART ANALYSIS | SIMULATION | EXECUTION VERIFICATION", className="magitek-note"),
                html.Div([
                    html.Span("PROTOCOL: ", className="fw-bold text-warning small me-2 align-middle font-monospace"),
                    dbc.RadioItems(
                        id='chart-mode-select',
                        options=[{'label': 'CALLS', 'value': 'call'}, {'label': 'PUTS', 'value': 'put'}],
                        value='call',
                        inline=True,
                        class_name="btn-group",
                        input_class_name="btn-check",
                        label_class_name="btn btn-outline-secondary btn-sm font-monospace",
                        label_checked_class_name="active"
                    )
                ], className="d-inline-block mt-1")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: DEEP SCAN", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("1. TARGETING", className="card-header"),
                    dbc.CardBody([
                        html.Label("Mission Date", className="small text-muted font-monospace"), 
                        dcc.Dropdown(id='chart-date-dropdown', placeholder="Select Day...", className="mb-2"),
                        html.Label("Signal ID", className="small text-muted font-monospace"), 
                        dcc.Dropdown(id='chart-signal-dropdown', placeholder="Scanning options...")
                    ])
                ], className="h-100 shadow-sm")
            ], width=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("2. WHAT-IF SIMULATOR", className="card-header"),
                    dbc.CardBody([
                        html.Label("Simulated Trailing Stop %", className="small text-muted font-monospace"),
                        dcc.Slider(min=5, max=50, step=5, value=20, marks={5:'5%', 10:'10%', 20:'20%', 30:'30%', 50:'50%'}, id='stop-loss-slider'),
                        html.Div(id='sim-feedback', className="text-end small text-white mt-2 font-monospace")
                    ])
                ], className="h-100 shadow-sm")
            ], width=8)
        ], className="mb-3"),

        dbc.Row([dbc.Col([dcc.Loading(dcc.Graph(id='chart-main-display', style={'height': '900px'}, config={'displayModeBar': False}))], width=12)])
    ], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    [Output('chart-date-dropdown', 'options'), Output('chart-date-dropdown', 'value')],
    Input('chart-mode-select', 'value')
)
def update_date_dropdown(mode):
    options = fetch_unique_dates(mode)
    return options, options[0]['value'] if options else None

@callback(
    [Output('chart-signal-dropdown', 'options'), Output('chart-signal-dropdown', 'value')],
    [Input('chart-date-dropdown', 'value'), Input('chart-mode-select', 'value')]
)
def update_signal_dropdown(date_str, mode):
    if not date_str: return [], None
    options, best_val = scout_day_performance(date_str, mode)
    return options, best_val

@callback(
    [Output('chart-main-display', 'figure'), Output('sim-feedback', 'children')],
    [Input('chart-signal-dropdown', 'value'), Input('stop-loss-slider', 'value')],
    [State('chart-mode-select', 'value')]
)
def update_chart(entry_ts, stop_pct, mode):
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if not entry_ts: return empty_fig, ""

    if not config.DB_FILE.exists(): return empty_fig, "DB Error"
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    res = con.execute(f"SELECT xsp_price, trade_type FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts}").fetchone()
    con.close()
    if not res: return empty_fig, "Signal Not Found"
    
    xsp_est, trade_type = res[0], res[1]
    
    # FETCH DATA
    opt_df, ticker = fetch_trade_performance(entry_ts, trade_type, xsp_est, stop_pct)
    xsp_df, vix_df, es_df = fetch_indicators(entry_ts)
    fills = fetch_executions(entry_ts, 'XSP')

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.3, 0.25, 0.25, 0.2], 
                        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
                        subplot_titles=("CONTEXT: XSP + SMA (X-RAY)", f"FORENSICS: {ticker}", "VIX FRACTAL FLOW", "VIX RSI (CHOP ZONE)"))

    has_data = False

    # 1. XSP + ES + SMA
    if not xsp_df.empty:
        fig.add_trace(go.Candlestick(x=xsp_df.index, open=xsp_df['open'], high=xsp_df['high'], low=xsp_df['low'], close=xsp_df['close'], name="XSP"), row=1, col=1)
        # X-RAY: SMA 50
        fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['sma_50'], name="Fractal Line (SMA50)", line=dict(color='orange', width=1)), row=1, col=1)
        has_data = True

    if not es_df.empty:
        fig.add_trace(go.Scatter(x=es_df.index, y=es_df['scaled_close'], name="/ES (x0.1)", line=dict(color='#00d2ff', width=1, dash='dot')), row=1, col=1)

    # 2. P&L + PRICE + SIMULATION + FILLS
    if opt_df is not None and not opt_df.empty:
        has_data = True
        colors = ['rgba(0, 188, 140, 0.3)' if v >= 0 else 'rgba(231, 76, 60, 0.3)' for v in opt_df['pnl_pct']]
        
        # Real P&L
        fig.add_trace(go.Bar(x=opt_df['datetime_local'], y=opt_df['pnl_pct'], name="Actual P&L %", marker_color=colors), row=2, col=1, secondary_y=False)
        
        # Simulated P&L (Line)
        fig.add_trace(go.Scatter(x=opt_df['datetime_local'], y=opt_df['sim_pnl_pct'], name=f"Sim P&L ({stop_pct}% Trail)", line=dict(color='yellow', width=2, dash='dot')), row=2, col=1, secondary_y=False)
        
        # Option Price
        fig.add_trace(go.Scatter(x=opt_df['datetime_local'], y=opt_df['open'], name="Option Price", line=dict(color='white', width=1.5)), row=2, col=1, secondary_y=True)
        
        # FORENSICS: Plot Actual Fills
        if not fills.empty:
             fig.add_trace(go.Scatter(x=fills['datetime_local'], y=[0]*len(fills), mode='markers', name="EXECUTION FILL", marker=dict(symbol='circle', size=15, color='yellow', line=dict(width=2, color='white'))), row=2, col=1, secondary_y=False)

    # 3. MACD
    if not vix_df.empty:
        fig.add_trace(go.Bar(x=vix_df.index, y=vix_df['hist'], name="Macro (1h)", marker_color='rgba(255, 255, 255, 0.2)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['macd'], name="Micro (5m)", line=dict(color='#f1c40f', width=1)), row=3, col=1)
        
        # 4. RSI + CHOP ZONES
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5)), row=4, col=1)
        # Chop Zone (30-70)
        fig.add_hrect(y0=30, y1=70, fillcolor="gray", opacity=0.1, layer="below", line_width=0, row=4, col=1)
        # Bull/Bear Zones
        fig.add_hrect(y0=70, y1=100, fillcolor="red", opacity=0.1, layer="below", line_width=0, row=4, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor="green", opacity=0.1, layer="below", line_width=0, row=4, col=1)
        
        has_data = True

    entry_wc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc).astimezone(config.TZ_LOCAL).replace(tzinfo=None)
    if not has_data:
        empty_fig.add_annotation(text="DATA UNAVAILABLE", showarrow=False, font=dict(size=20, color="red"))
        return empty_fig, ""
        
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=50, r=50, t=30, b=100), showlegend=True, height=900, legend=dict(orientation="h", yanchor="top", y=-0.05, xanchor="center", x=0.5))
  # FIX: Split vline and annotation to avoid Plotly datetime math bug
    fig.add_vline(x=entry_wc, line_width=1, line_dash="dash", line_color="lime")
    
    # Manually place the label at the top of the chart
    fig.add_annotation(
        x=entry_wc, 
        y=1.0, 
        yref="paper",
        text="SIGNAL",
        showarrow=False,
        font=dict(color="lime", size=10, weight="bold"),
        bgcolor="rgba(0,0,0,0.5)"
    )
    
    # --------------------------------------------------------------------------
    # SIMULATION FEEDBACK
    # --------------------------------------------------------------------------
    sim_msg = f"Simulating {stop_pct}% Trailing Stop"
    return fig, sim_msg