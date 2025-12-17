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
# 2. HELPER FUNCTIONS
# ==============================================================================
def to_wall_clock(series):
    if series.empty: return series
    if series.dt.tz is None:
        series = series.dt.tz_localize('UTC')
    else:
        series = series.dt.tz_convert('UTC')
    series = series.dt.tz_convert(config.TZ_LOCAL)
    return series.dt.tz_localize(None)

def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df = df.copy()
    df['x'] = np.arange(len(df))
    slope, intercept = np.polyfit(df['x'], df['close'], 1)
    df['reg_line'] = slope * df['x'] + intercept
    std = df['close'].std()
    df['upper_band'] = df['reg_line'] + (2 * std)
    df['lower_band'] = df['reg_line'] - (2 * std)
    return df

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
    except Exception as e: return []

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
        con.close()
        
        if signals.empty: return [], None

        options_list = []
        best_ts = None
        
        for i, row in signals.iterrows():
            ts = row['entry_timestamp_utc']
            entry_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
            time_str = entry_dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
            clean_meta = str(row['meta_data']).replace('VIX_FRACTAL_LONG', '').replace('VIX_FRACTAL_SHORT', '').strip()
            if "|" in clean_meta: clean_meta = clean_meta.split('|')[-1].strip()
            
            label = f"Signal #{i+1} ({time_str}) | {clean_meta}"
            options_list.append({'label': label, 'value': ts})
            
            if i == 0: best_ts = ts

        return options_list, best_ts
    except Exception as e:
        return [], None

def fetch_available_strikes(entry_ts, trade_type):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        res = con.execute(f"SELECT xsp_price, date FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts}").fetchone()
        
        if not res: 
            con.close(); return [], None
            
        xsp_price, date_val = res
        target_strike = round(float(xsp_price))
        
        dt = date_val if isinstance(date_val, (datetime, pd.Timestamp)) else datetime.strptime(str(date_val), '%Y-%m-%d')
        date_fmt = dt.strftime('%y%m%d')
        opt_code = 'C' if trade_type.upper() == 'CALL' else 'P'
        
        like_pattern = f"O:XSP{date_fmt}{opt_code}%"
        tickers = con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS} WHERE ticker LIKE '{like_pattern}'").fetchall()
        con.close()
        
        if not tickers: return [], None
        
        temp_options = []
        atm_ticker = None
        min_dist = float('inf')
        
        for t in tickers:
            ticker = t[0]
            try:
                strike_val = int(ticker[-8:]) / 1000.0
                diff = strike_val - target_strike
                
                if diff == 0: label = f"{strike_val:.0f} (ATM)"
                elif diff > 0: label = f"{strike_val:.0f} (+{int(diff)})"
                else: label = f"{strike_val:.0f} ({int(diff)})"
                
                temp_options.append({'label': label, 'value': ticker, 'strike': strike_val})
                
                if abs(diff) < min_dist:
                    min_dist = abs(diff)
                    atm_ticker = ticker
            except: continue
            
        temp_options.sort(key=lambda x: x['strike'])
        final_options = [{'label': x['label'], 'value': x['value']} for x in temp_options]
        
        return final_options, atm_ticker

    except Exception as e:
        print(f"Strike Fetch Error: {e}")
        return [], None

def fetch_trade_performance(entry_ts_ms, ticker, sim_stop_pct=20):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_OPTIONS not in tables:
             con.close(); return None, {}

        entry_dt_utc = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).replace(tzinfo=None)
        
        # Determine RTH window
        entry_dt_ny = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        day_date = entry_dt_ny.date()
        start_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        end_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        query = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
        df = con.execute(query).df()
        con.close()

        if df.empty: return None, {}

        temp = df.copy()
        temp['datetime_utc'] = pd.to_datetime(temp['datetime_utc'])
        if temp['datetime_utc'].dt.tz is not None:
             temp['datetime_utc'] = temp['datetime_utc'].dt.tz_convert(None)
        
        idx = temp['datetime_utc'].sub(entry_dt_utc).abs().idxmin()
        df = df.loc[idx:].copy()
        
        entry_price = 0.0
        for px in df['open'].head(30):
            if px > 0.01:
                entry_price = px
                break
        
        if entry_price == 0.0 and not df.empty: entry_price = df.iloc[0]['open']
        if entry_price < 0.01: entry_price = 0.01

        df['pnl_pct'] = ((df['open'] - entry_price) / entry_price) * 100
        
        max_price = df['high'].max()
        max_gain = ((max_price - entry_price) / entry_price) * 100
        sim_exit_pct = df.iloc[-1]['pnl_pct']
        
        stop_mult = 1.0 - (sim_stop_pct / 100.0)
        df['rolling_max'] = df['high'].cummax()
        df['stop_level'] = df['rolling_max'] * stop_mult
        
        stop_hits = df[df['low'] < df['stop_level']]
        df['sim_pnl_pct'] = df['pnl_pct']
        
        if not stop_hits.empty:
            first_stop_idx = stop_hits.index[0]
            sim_exit_pct = df.loc[first_stop_idx, 'pnl_pct']
            df.loc[first_stop_idx:, 'sim_pnl_pct'] = sim_exit_pct
            
        stats = {
            "entry": entry_price,
            "max_price": max_price,
            "max_gain": max_gain,
            "sim_exit": sim_exit_pct
        }
            
        df['datetime_local'] = to_wall_clock(df['datetime_utc'])
        return df, stats
    except Exception as e: 
        print(f"Trade Perf Error: {e}")
        return None, {}

def fetch_executions(entry_ts_ms, root):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if 'active_rh_log' not in tables:
             con.close(); return pd.DataFrame()
             
        sig_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc)
        s_start = (sig_dt - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
        s_end = (sig_dt + timedelta(minutes=120)).strftime('%Y-%m-%d %H:%M:%S')
        
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
             try: 
                 df_fut = con.execute(f"SELECT datetime_utc, ticker, close FROM {tbl_fut} WHERE (ticker LIKE 'ES%' OR ticker = '/ES') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
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
                xsp['sma_50'] = xsp['close'].rolling(50).mean()
                xsp = calculate_linreg(xsp)

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
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("LIBRA SCAN COMMAND", className="magitek-h2"),
                html.P("FORENSIC CHART ANALYSIS | SIMULATION | RTH ONLY", className="magitek-note"),
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
                html.Div("FILTER: RTH (09:30-16:00)", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "color": "#f3f5f9", "boxShadow": "0px 0px 10px rgba(0,0,0,0.5)"}),

        # 3-COLUMN LAYOUT
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("1. TARGETING", className="card-header"),
                    dbc.CardBody([
                        html.Label("Mission Date", className="small text-muted font-monospace"), 
                        dcc.Dropdown(id='chart-date-dropdown', placeholder="Select Day...", className="mb-2"),
                        html.Label("Signal ID", className="small text-muted font-monospace"), 
                        dcc.Dropdown(id='chart-signal-dropdown', placeholder="Scanning options...", className="mb-2"),
                        html.Label("Strike Selection", className="small text-muted font-monospace"),
                        dcc.Dropdown(id='chart-strike-dropdown', placeholder="Select Strike...", style={"fontFamily": "monospace"})
                    ])
                ], className="h-100 shadow-sm")
            ], width=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("2. COMBAT REPORT", className="card-header"),
                    dbc.CardBody(id='signal-report-card', className="d-flex align-items-center justify-content-center h-100")
                ], className="h-100 shadow-sm")
            ], width=4),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("3. WHAT-IF SIMULATOR", className="card-header"),
                    dbc.CardBody([
                        html.Label("Simulated Trailing Stop %", className="small text-muted font-monospace"),
                        dcc.Slider(min=5, max=50, step=5, value=20, marks={5:'5%', 10:'10%', 20:'20%', 30:'30%', 50:'50%'}, id='stop-loss-slider'),
                        html.Div(id='sim-feedback', className="text-end small text-white mt-2 font-monospace")
                    ])
                ], className="h-100 shadow-sm")
            ], width=4)
        ], className="mb-3"),

        # CHART (No Loading Spinner)
        dbc.Row([dbc.Col([dcc.Graph(id='chart-main-display', style={'height': '900px'}, config={'displayModeBar': True})], width=12)])
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
    [Output('chart-strike-dropdown', 'options'), Output('chart-strike-dropdown', 'value')],
    [Input('chart-signal-dropdown', 'value')],
    [State('chart-mode-select', 'value')]
)
def update_strike_options(entry_ts, mode):
    if not entry_ts: return [], None
    options, atm_ticker = fetch_available_strikes(entry_ts, mode)
    return options, atm_ticker

@callback(
    [Output('chart-main-display', 'figure'), 
     Output('signal-report-card', 'children'),
     Output('sim-feedback', 'children')],
    [Input('chart-signal-dropdown', 'value'), 
     Input('chart-strike-dropdown', 'value'),
     Input('stop-loss-slider', 'value')],
    [State('chart-mode-select', 'value')]
)
def update_chart(entry_ts, ticker, stop_pct, mode):
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if not entry_ts or not ticker: return empty_fig, "NO DATA", ""

    if not config.DB_FILE.exists(): return empty_fig, "DB MISSING", ""
    
    # FETCH DATA
    opt_df, stats = fetch_trade_performance(entry_ts, ticker, stop_pct)
    xsp_df, vix_df, es_df = fetch_indicators(entry_ts)
    fills = fetch_executions(entry_ts, 'XSP')

    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.35, 0.25, 0.2, 0.2], 
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("CONTEXT: XSP + LinReg + ES(x0.1)", f"FORENSICS: {ticker}", "VIX FRACTAL FLOW", "VIX RSI")
    )

    has_data = False
    
    entry_wc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc).astimezone(config.TZ_LOCAL).replace(tzinfo=None)
    day_start = entry_wc.replace(hour=6, minute=30, second=0)
    day_end = entry_wc.replace(hour=13, minute=0, second=0)

    # 1. XSP + LinReg + ORB (Row 1)
    if not xsp_df.empty:
        # ORB
        start_window = day_start
        end_window = day_start + timedelta(minutes=30)
        orb_df = xsp_df[(xsp_df.index >= start_window) & (xsp_df.index <= end_window)]
        orb_h = orb_df['high'].max() if not orb_df.empty else None
        orb_l = orb_df['low'].min() if not orb_df.empty else None

        fig.add_trace(go.Candlestick(x=xsp_df.index, open=xsp_df['open'], high=xsp_df['high'], low=xsp_df['low'], close=xsp_df['close'], name="XSP"), row=1, col=1)
        
        if 'reg_line' in xsp_df.columns:
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)
            
            # Ghost Lines Row 2
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['reg_line'], line=dict(color='yellow', width=1, dash='dot'), showlegend=False), row=2, col=1, secondary_y=False)
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['upper_band'], line=dict(color='cyan', width=1), showlegend=False), row=2, col=1, secondary_y=False)
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['lower_band'], line=dict(color='cyan', width=1), showlegend=False), row=2, col=1, secondary_y=False)

        if orb_h and orb_l:
            fig.add_hline(y=orb_h, line_dash="solid", line_color="green", opacity=0.5, row=1, col=1)
            fig.add_hline(y=orb_l, line_dash="solid", line_color="red", opacity=0.5, row=1, col=1)
            # Ghost ORB Row 2
            fig.add_hline(y=orb_h, line_dash="solid", line_color="green", opacity=0.3, row=2, col=1)
            fig.add_hline(y=orb_l, line_dash="solid", line_color="red", opacity=0.3, row=2, col=1)

        has_data = True

    if not es_df.empty:
        fig.add_trace(go.Scatter(x=es_df.index, y=es_df['scaled_close'], name="/ES (x0.1)", line=dict(color='#00d2ff', width=1, dash='dot')), row=1, col=1)

    # 2. OPTIONS (Row 2) - CLEAN CANDLES (Replay Style)
    if opt_df is not None and not opt_df.empty:
        has_data = True
        
        # ⚡ OPTION CANDLES
        fig.add_trace(go.Candlestick(
            x=opt_df['datetime_local'],
            open=opt_df['open'], high=opt_df['high'],
            low=opt_df['low'], close=opt_df['close'],
            name="Option",
            hoverlabel=dict(bgcolor="#1e1e1e", font=dict(color="white", family="monospace"))
        ), row=2, col=1, secondary_y=False)
        
        # Sim Line
        fig.add_trace(go.Scatter(x=opt_df['datetime_local'], y=opt_df['sim_pnl_pct'], name="Sim Stop", line=dict(color='yellow', width=2, dash='dot')), row=2, col=1, secondary_y=False)
        
        # Thin White Line (Matching Replay)
        fig.add_trace(go.Scatter(x=opt_df['datetime_local'], y=opt_df['open'], name="Price", line=dict(color='white', width=1)), row=2, col=1, secondary_y=True)
        
        if not fills.empty:
             fig.add_trace(go.Scatter(x=fills['datetime_local'], y=fills['avg_price'], mode='markers', name="FILL", marker=dict(symbol='circle', size=12, color='cyan', line=dict(width=2, color='white'))), row=2, col=1, secondary_y=True)

    # 3. VIX Fractal (Row 3)
    if not vix_df.empty:
        fig.add_trace(go.Bar(x=vix_df.index, y=vix_df['hist'], name="Hist", marker_color='rgba(255, 255, 255, 0.3)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['macd'], name="MACD", line=dict(color='#f1c40f', width=1)), row=3, col=1)

    # 4. RSI (Row 4)
    if not vix_df.empty:
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5, shape='spline')), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=4, col=1)

    if not has_data:
        empty_fig.add_annotation(text="DATA UNAVAILABLE", showarrow=False, font=dict(size=20, color="red"))
        return empty_fig, "NO DATA", ""
        
    # ⚡ ZOOM LOCKED
    fig.update_xaxes(matches='x', range=[day_start, day_end], type='date', fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    
    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=30, b=40), 
        showlegend=False, 
        height=900,
        hovermode="x unified",
        font=dict(family="'VT323', monospace", size=14, color="#f3f5f9"),
        hoverlabel=dict(bgcolor="#1e1e1e", font=dict(color="#f3f5f9", family="monospace"))
    )
    
    fig.add_vline(x=entry_wc, line_width=1, line_dash="dash", line_color="lime", row=1, col=1)
    fig.add_annotation(x=entry_wc, y=1.0, yref="paper", text="SIGNAL", showarrow=False, font=dict(color="lime", size=10), bgcolor="rgba(0,0,0,0.5)")
    
    # --- REPORT CARD GENERATION ---
    entry = stats.get('entry', 0)
    max_gain = stats.get('max_gain', 0)
    sim_exit = stats.get('sim_exit', 0)
    
    # Safe coloring logic for formatted string
    sim_color = 'text-success' if sim_exit > 0 else 'text-danger'
    
    report_html = html.Div([
        dbc.Row([
            dbc.Col([html.Div("ENTRY PRICE", className="small text-muted"), html.Div(f"${entry:.2f}", className="fw-bold text-white")], width=4),
            dbc.Col([html.Div("MAX POTENTIAL", className="small text-muted"), html.Div(f"+{max_gain:.1f}%", className="fw-bold text-success")], width=4),
            dbc.Col([html.Div("SIM RESULT", className="small text-muted"), html.Div(f"+{sim_exit:.1f}%", className=f"fw-bold {sim_color}")], width=4),
        ])
    ], className="text-center font-monospace")

    sim_msg = f"Simulating {stop_pct}% Trailing Stop"
    return fig, report_html, sim_msg