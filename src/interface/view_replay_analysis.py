import dash
from dash import dcc, html, callback, Input, Output, State, no_update
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
# 1. SETUP
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def to_wall_clock(series):
    if series.empty: return series
    if series.dt.tz is None: series = series.dt.tz_localize('UTC')
    else: series = series.dt.tz_convert('UTC')
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

def fetch_unique_dates(trade_type_filter='call'):
    try:
        if not config.DB_FILE.exists(): return []
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_INDICES not in tables: 
             con.close(); return []

        t_filter = trade_type_filter.upper()
        q_dates = f"SELECT DISTINCT CAST(datetime_utc AS DATE) as d FROM {config.TBL_INDICES} WHERE ticker='XSP' ORDER BY d DESC"
        df_dates = con.execute(q_dates).df()
        
        if config.TBL_MANIFEST in tables:
            q_sigs = f"SELECT date, COUNT(*) as sig_count FROM {config.TBL_MANIFEST} WHERE trade_type = '{t_filter}' GROUP BY date"
            try: df_sigs = con.execute(q_sigs).df()
            except: df_sigs = pd.DataFrame()
        else: df_sigs = pd.DataFrame()
        
        con.close()
        
        if df_dates.empty: return []
        df_dates['d'] = pd.to_datetime(df_dates['d'])
        
        if not df_sigs.empty:
            df_sigs['date'] = pd.to_datetime(df_sigs['date'])
            merged = pd.merge(df_dates, df_sigs, left_on='d', right_on='date', how='left')
            merged['sig_count'] = merged['sig_count'].fillna(0).astype(int)
        else:
            merged = df_dates
            merged['sig_count'] = 0
            
        return [{'label': f"{r['d'].strftime('%Y-%m-%d')} ({r['sig_count']} Signals)", 'value': r['d'].strftime('%Y-%m-%d')} for _, r in merged.iterrows()]
    except: return []

def scout_day_performance(date_str, trade_type_filter='call'):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        t_type = trade_type_filter.upper()
        signals = pd.DataFrame()
        try:
            signals = con.execute(f"SELECT entry_timestamp_utc, xsp_price, meta_data FROM {config.TBL_MANIFEST} WHERE trade_type = '{t_type}' AND date = '{date_str}' ORDER BY entry_timestamp_utc ASC").df()
        except: pass
        con.close()
        
        options = []
        best_ts = None
        if not signals.empty:
            for i, row in signals.iterrows():
                ts = row['entry_timestamp_utc']
                dt_local = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_LOCAL)
                label = f"Signal #{i+1} @ {dt_local.strftime('%H:%M')} | XSP {row['xsp_price']:.2f}"
                options.append({'label': label, 'value': ts})
                if i == 0: best_ts = ts
        else:
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            open_ts = config.TZ_NY.localize(datetime.combine(dt, time(9, 30))).timestamp() * 1000
            options.append({'label': "09:30 Market Open (Review)", 'value': open_ts})
            best_ts = open_ts
        return options, best_ts
    except: return [], None

def fetch_available_strikes_for_replay(entry_ts, trade_type):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        entry_dt = datetime.fromtimestamp(entry_ts/1000, tz=pytz.utc)
        s_str = entry_dt.strftime('%Y-%m-%d %H:%M:%S')
        res = con.execute(f"SELECT close FROM {config.TBL_INDICES} WHERE ticker='XSP' AND datetime_utc <= '{s_str}' ORDER BY datetime_utc DESC LIMIT 1").fetchone()
        xsp_price = res[0] if res else 0
        
        date_fmt = entry_dt.strftime('%y%m%d')
        opt = 'C' if trade_type.upper() == 'CALL' else 'P'
        like_pat = f"XSP{date_fmt}{opt}%"
        tickers = con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS} WHERE ticker LIKE '{like_pat}'").fetchall()
        con.close()
        
        if not tickers: return [], None
        opts = []
        target = round(xsp_price)
        atm_ticker = None
        min_dist = float('inf')
        for t in tickers:
            tk = t[0]
            try:
                strike = int(tk[-8:]) / 1000.0
                dist = abs(strike - target)
                label = f"{strike:.0f} (ATM)" if dist < 1 else f"{strike:.0f}"
                opts.append({'label': label, 'value': tk, 'dist': dist})
                if dist < min_dist:
                    min_dist = dist
                    atm_ticker = tk
            except: continue
        opts.sort(key=lambda x: x['dist'])
        return [{'label': x['label'], 'value': x['value']} for x in opts], atm_ticker
    except: return [], None

def load_replay_tape(entry_ts, ticker):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        entry_dt = datetime.fromtimestamp(entry_ts/1000, tz=pytz.utc)
        dt_date = entry_dt.date()
        s_str = config.TZ_NY.localize(datetime.combine(dt_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        e_str = config.TZ_NY.localize(datetime.combine(dt_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        df_idx = con.execute(f"SELECT datetime_utc, ticker, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker IN ('XSP','VIX') AND datetime_utc BETWEEN '{s_str}' AND '{e_str}' ORDER BY datetime_utc").df()
        df_opt = pd.DataFrame()
        if ticker:
            try: df_opt = con.execute(f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' AND datetime_utc BETWEEN '{s_str}' AND '{e_str}' ORDER BY datetime_utc").df()
            except: pass
        con.close()
        
        xsp = df_idx[df_idx['ticker']=='XSP'].copy() if not df_idx.empty else pd.DataFrame()
        if not xsp.empty:
            xsp['dt'] = to_wall_clock(pd.to_datetime(xsp['datetime_utc']))
            xsp = xsp.sort_values('dt')
            xsp = calculate_linreg(xsp)
            
        vix = df_idx[df_idx['ticker']=='VIX'].copy() if not df_idx.empty else pd.DataFrame()
        if not vix.empty:
            vix['dt'] = to_wall_clock(pd.to_datetime(vix['datetime_utc']))
            vix = vix.sort_values('dt')
            vix['macd'] = vix['close'].ewm(span=12).mean() - vix['close'].ewm(span=26).mean()
            vix['hist'] = vix['macd'] - vix['macd'].ewm(span=9).mean()
            delta = vix['close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            vix['rsi'] = 100 - (100 / (1 + rs))

        opt = pd.DataFrame()
        entry_price = 0.0
        if not df_opt.empty:
            opt = df_opt.copy()
            opt['dt'] = to_wall_clock(pd.to_datetime(opt['datetime_utc']))
            opt = opt.sort_values('dt')
            entry_local = entry_dt.astimezone(config.TZ_LOCAL).replace(tzinfo=None)
            try:
                idx = opt['dt'].sub(entry_local).abs().idxmin()
                entry_price = opt.loc[idx, 'open']
            except: entry_price = opt.iloc[0]['open'] if len(opt) > 0 else 0

        return {'xsp': xsp.to_dict('records'), 'vix': vix.to_dict('records'), 'opt': opt.to_dict('records'), 'entry_ts': entry_ts, 'ticker': ticker, 'entry_price': entry_price}
    except Exception as e:
        print(f"Tape Error: {e}")
        return None

# ==============================================================================
# 3. LAYOUT
# ==============================================================================
def render():
    # ⚡ FORCED HIGH-CONTRAST FOR DROPDOWNS
    DROPDOWN_STYLE = {'color': '#000000', 'backgroundColor': '#ffffff', 'fontFamily': 'monospace'} 

    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("MARKET REPLAY ENGINE", className="fw-bold text-white mb-0"),
                html.P("HISTORICAL SIMULATION & STRATEGY REVIEW", className="text-muted small fw-bold mb-0")
            ], width=8),
            dbc.Col([
                html.Div([
                    html.Span("PROTOCOL: ", className="fw-bold text-warning small me-2"),
                    dbc.RadioItems(
                        id='replay-mode-select',
                        options=[{'label': 'CALLS', 'value': 'call'}, {'label': 'PUTS', 'value': 'put'}],
                        value='call',
                        inline=True,
                        class_name="btn-group",
                        input_class_name="btn-check",
                        label_class_name="btn btn-outline-secondary btn-sm",
                        label_checked_class_name="active"
                    )
                ], className="text-end")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("1. MISSION DATE", className="small text-muted fw-bold"),
                        dcc.Dropdown(id='replay-date-dropdown', placeholder="Select Date...", style=DROPDOWN_STYLE),
                        html.Label("2. TARGET SIGNAL", className="small text-muted fw-bold"),
                        dcc.Dropdown(id='replay-signal-dropdown', placeholder="Select Signal...", style=DROPDOWN_STYLE),
                        html.Label("3. OPTION CONTRACT", className="small text-muted fw-bold"),
                        dcc.Dropdown(id='replay-strike-dropdown', placeholder="Select Strike...", style=DROPDOWN_STYLE)
                    ], width=4),
                    
                    dbc.Col([
                        html.Label("4. PLAYBACK CONTROLS", className="small text-muted fw-bold d-block"),
                        dbc.ButtonGroup([
                            dbc.Button("▶ PLAY", id="btn-play", color="success", n_clicks=0, className="fw-bold"),
                            dbc.Button("⏸ PAUSE", id="btn-pause", color="warning", n_clicks=0, className="fw-bold"),
                            dbc.Button("⏪ RESET", id="btn-reset", color="danger", n_clicks=0, className="fw-bold"),
                        ], className="w-100 mb-2"),
                        html.Div([
                            html.Label("SPEED:", className="small text-muted fw-bold me-2"),
                            dbc.RadioItems(
                                id="speed-selector",
                                options=[{"label": "1x", "value": 1000}, {"label": "5x", "value": 200}, {"label": "MAX", "value": 50}],
                                value=200, inline=True, className="text-white"
                            )
                        ], className="text-center")
                    ], width=4),
                    
                    dbc.Col([
                        html.Label("5. STATUS", className="small text-muted fw-bold d-block"),
                        dbc.Checklist(
                            options=[{"label": "REVEAL STRATEGY", "value": "show"}],
                            value=[], id="show-signal-toggle", switch=True,
                            labelClassName="text-warning fw-bold small"
                        ),
                        html.H2(id="clock-display", className="text-info text-end fw-bold mt-2", children="09:30"),
                        html.Div(id="frame-info", className="text-end text-muted small", children="Frame: 0"),
                        html.Div(id="combat-metric-display", className="mt-2 font-monospace text-end")
                    ], width=4)
                ]),
                dbc.Row([
                    dbc.Col(dcc.Slider(id='timeline-slider', min=0, max=390, step=1, value=0, 
                                     marks={0:'Open', 390:'Close'}, tooltip={"placement":"bottom"}), width=12, className="mt-3")
                ])
            ])
        ], className="mb-3 border-secondary"),

        dbc.Row([dbc.Col(dcc.Graph(id='replay-chart', style={'height': '75vh'}, config={'displayModeBar': True}), width=12)]),
        
        dcc.Store(id='replay-tape-store'),
        dcc.Interval(id='replay-interval', interval=1000, n_intervals=0, disabled=True)
    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================

# A. Data Loading
@callback(
    [Output('replay-date-dropdown', 'options'), Output('replay-date-dropdown', 'value')],
    Input('replay-mode-select', 'value')
)
def update_dates(mode):
    opts = fetch_unique_dates(mode)
    return opts, opts[0]['value'] if opts else None

@callback(
    [Output('replay-signal-dropdown', 'options'), Output('replay-signal-dropdown', 'value')],
    [Input('replay-date-dropdown', 'value'), Input('replay-mode-select', 'value')]
)
def update_signals(date, mode):
    if not date: return [], None
    return scout_day_performance(date, mode)

@callback(
    [Output('replay-strike-dropdown', 'options'), Output('replay-strike-dropdown', 'value')],
    [Input('replay-signal-dropdown', 'value')], [State('replay-mode-select', 'value')]
)
def update_strikes(ts, mode):
    if not ts: return [], None
    return fetch_available_strikes_for_replay(ts, mode)

@callback(
    [Output('replay-tape-store', 'data'), Output('timeline-slider', 'max'), Output('timeline-slider', 'value', allow_duplicate=True)],
    [Input('replay-signal-dropdown', 'value'), Input('replay-strike-dropdown', 'value')],
    prevent_initial_call=True
)
def load_data(ts, ticker):
    if not ts: return no_update, 390, 0
    pkt = load_replay_tape(ts, ticker)
    if not pkt: return None, 390, 0
    return pkt, len(pkt['xsp'])-1, 0

# B. Motor
@callback(
    [Output('timeline-slider', 'value'), Output('replay-interval', 'disabled', allow_duplicate=True)],
    [Input('replay-interval', 'n_intervals')],
    [State('timeline-slider', 'value'), State('timeline-slider', 'max')],
    prevent_initial_call=True
)
def advance_slider(n, val, max_val):
    if val is None: return 0, True
    if val < max_val: return val + 1, no_update
    return val, True 

# C. Controls
@callback(
    [Output('replay-interval', 'disabled'), Output('replay-interval', 'interval'), Output('timeline-slider', 'value', allow_duplicate=True)],
    [Input('btn-play', 'n_clicks'), Input('btn-pause', 'n_clicks'), Input('btn-reset', 'n_clicks'), Input('speed-selector', 'value')],
    prevent_initial_call=True
)
def control_playback(play, pause, reset, speed):
    ctx = dash.callback_context
    if not ctx.triggered: return True, 200, no_update
    trig = ctx.triggered[0]['prop_id'].split('.')[0]
    spd = int(speed) if speed else 200
    if trig == 'btn-play': return False, spd, no_update
    if trig == 'btn-pause': return True, spd, no_update
    if trig == 'btn-reset': return True, spd, 0
    return no_update, spd, no_update

# D. Render Frame
@callback(
    [Output('replay-chart', 'figure'), Output('clock-display', 'children'), Output('frame-info', 'children'), Output('combat-metric-display', 'children')],
    [Input('timeline-slider', 'value'), Input('show-signal-toggle', 'value'), Input('replay-tape-store', 'data')]
)
def update_chart(idx, show, pkt):
    if not pkt or idx is None: 
        fig = go.Figure()
        fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', xaxis_visible=False, yaxis_visible=False)
        return fig, "--:--", "Frame: 0", ""

    xsp = pd.DataFrame(pkt['xsp'])
    vix = pd.DataFrame(pkt['vix'])
    opt = pd.DataFrame(pkt['opt'])
    c_idx = min(idx, len(xsp)-1)
    xsp_s = xsp.iloc[:c_idx+1]
    
    if xsp_s.empty: return go.Figure(), "--:--", "Frame: 0", ""
    curr_dt = pd.to_datetime(xsp_s.iloc[-1]['dt'])
    
    entry_ts = pkt['entry_ts']
    entry_price = pkt.get('entry_price', 0)
    
    # ⚡ CRITICAL FIX: Pandas TypeError Workaround
    # Do NOT use annotation_text inside add_vline. It tries to sum() the Timestamp.
    entry_local = pd.to_datetime(entry_ts, unit='ms').tz_localize('UTC').tz_convert(config.TZ_LOCAL).tz_localize(None)

    # 4-ROW LAYOUT
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.35, 0.25, 0.20, 0.20],
                        subplot_titles=("XSP Index", "Strategy (Option)", "VIX Momentum", "VIX RSI"))
    
    # Row 1: XSP
    fig.add_trace(go.Candlestick(x=xsp_s['dt'], open=xsp_s['open'], high=xsp_s['high'], low=xsp_s['low'], close=xsp_s['close'], name="XSP"), row=1, col=1)
    if 'reg_line' in xsp_s.columns:
        fig.add_trace(go.Scatter(x=xsp_s['dt'], y=xsp_s['reg_line'], line=dict(color='#f1c40f', width=1, dash='dot'), name="Reg"), row=1, col=1)
    
    # ⚡ FIX: Add Line separately, then Annotation separately
    fig.add_vline(x=entry_local, line_dash="dash", line_color="yellow", row=1, col=1)
    
    # CORRECTED yref: 'y1 domain' -> 'y domain'
    fig.add_annotation(x=entry_local, y=0.95, yref='y domain', text="ENTRY", showarrow=False, font=dict(color="yellow"), row=1, col=1)
        
    # Row 2: Option (If Enabled)
    max_gain = 0.0
    if not opt.empty and 'show' in show:
        opt_s = opt[pd.to_datetime(opt['dt']) <= curr_dt]
        if not opt_s.empty:
            col = '#00bc8c' if opt_s.iloc[-1]['close'] >= opt_s.iloc[0]['open'] else '#ff5555'
            fig.add_trace(go.Candlestick(x=opt_s['dt'], open=opt_s['open'], high=opt_s['high'], low=opt_s['low'], close=opt_s['close'], 
                                         name="Option", increasing_line_color=col, decreasing_line_color=col), row=2, col=1)
            # Add line without annotation text to avoid crash
            fig.add_vline(x=entry_local, line_dash="dash", line_color="yellow", row=2, col=1)
            
            # Calculate Gain
            curr_opt = opt_s.iloc[-1]['close']
            if entry_price > 0:
                max_gain = ((curr_opt - entry_price) / entry_price) * 100

    # Row 3: VIX MACD
    if not vix.empty:
        vix_s = vix[pd.to_datetime(vix['dt']) <= curr_dt]
        if not vix_s.empty:
            cols = ['#ff5555' if v > 0 else '#00bc8c' for v in vix_s['hist']]
            fig.add_trace(go.Bar(x=vix_s['dt'], y=vix_s['hist'], marker_color=cols, name="Hist"), row=3, col=1)
            fig.add_trace(go.Scatter(x=vix_s['dt'], y=vix_s['macd'], line=dict(color='#f1c40f', width=1), name="MACD"), row=3, col=1)

    # Row 4: VIX RSI
    if not vix.empty:
        fig.add_trace(go.Scatter(x=vix_s['dt'], y=vix_s['rsi'], line=dict(color='#a855f7', width=2), name="RSI"), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ff5555", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    d_start = pd.to_datetime(xsp.iloc[0]['dt']).replace(hour=6, minute=30)
    d_end = d_start.replace(hour=13, minute=0)
    fig.update_xaxes(range=[d_start, d_end], row=4, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                      margin=dict(l=40, r=40, t=30, b=40), xaxis_rangeslider_visible=False, showlegend=False,
                      hovermode="x unified", uirevision=pkt['entry_ts'])

    # ⚡ FIX: High Contrast Silver Text for Metrics
    metric_color = "text-success" if max_gain > 0 else "text-danger" if max_gain < 0 else "text-muted"
    metric_text = html.Div([
        html.Span(f"P&L: {max_gain:+.1f}%", className=f"fw-bold {metric_color} fs-4"),
        html.Span(f" (Entry: ${entry_price:.2f})", style={'color': '#cccccc', 'fontSize': '0.9rem', 'marginLeft': '10px'})
    ])

    return fig, curr_dt.strftime('%H:%M'), f"Frame: {idx}", metric_text