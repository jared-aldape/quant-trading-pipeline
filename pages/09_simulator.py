import dash
from dash import dcc, html, Input, Output, State, register_page, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import duckdb
import pandas as pd
import numpy as np
import logging
from datetime import timedelta
from src.utils import config

# ==========================================
# 1. SETUP
# ==========================================
register_page(__name__, path='/simulator', name='Simulator')

logger = logging.getLogger("SimPilot")
STRIKE_RANGE = 2

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def clean_dataframe(df):
    # 1. Normalize Columns FIRST (Before checking empty)
    # This ensures the 'dt' column exists even if there are 0 rows
    if df is None: return pd.DataFrame()
    
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'close': 'close', 'vix_close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    
    # 2. NOW check empty
    if df.empty: return df
    
    # 3. Timezone Logic
    if 'dt' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['dt']):
            df['dt'] = pd.to_datetime(df['dt'])
        if df['dt'].dt.tz is None:
            df['dt'] = df['dt'].dt.tz_localize(config.TZ_UTC)
        else:
            df['dt'] = df['dt'].dt.tz_convert(config.TZ_UTC)
    return df

def clean_dataframe(df):
    if df.empty: return df
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'close': 'close', 'vix_close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    
    if 'dt' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['dt']):
            df['dt'] = pd.to_datetime(df['dt'])
        if df['dt'].dt.tz is None:
            df['dt'] = df['dt'].dt.tz_localize(config.TZ_UTC)
        else:
            df['dt'] = df['dt'].dt.tz_convert(config.TZ_UTC)
    return df

def calculate_indicators(df, prefix=''):
    if 'close' not in df.columns: return df
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df[f'{prefix}macd'] = ema12 - ema26
    df[f'{prefix}signal'] = df[f'{prefix}macd'].ewm(span=9, adjust=False).mean()
    df[f'{prefix}hist'] = df[f'{prefix}macd'] - df[f'{prefix}signal']
    
    # RSI
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False, min_periods=14).mean()
    ma_down = down.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = ma_up / ma_down
    df[f'{prefix}rsi'] = 100 - (100 / (1 + rs))
    return df

def get_signal_events():
    con = duckdb.connect(str(config.DB_FILE))
    try:
        query = f"SELECT date, entry_timestamp_utc, xsp_price FROM {config.TBL_MANIFEST} ORDER BY date DESC"
        df = con.execute(query).df()
    except: return []
    con.close()
    return [{'label': f"{row['date']} | Est. ATM: ${row['xsp_price']:.2f}", 'value': row['entry_timestamp_utc']} for _, row in df.iterrows()]

def get_tickers_for_event(event_ts):
    if not event_ts: return [], None
    con = duckdb.connect(str(config.DB_FILE))
    try:
        row = con.execute(f"SELECT date, xsp_price FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_ts}").df().iloc[0]
        trade_date = pd.to_datetime(row['date'])
        atm = round(row['xsp_price'])
        tickers = []
        best = None
        date_str = trade_date.strftime("%y%m%d")
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
            strike = atm + offset
            ticker = f"O:XSP{date_str}C{int(strike*1000):08d}"
            lbl = f"{ticker} ({'ATM' if offset==0 else 'OTM' if offset>0 else 'ITM'} ${strike})"
            tickers.append({'label': lbl, 'value': ticker})
            if offset == 0: best = ticker
        con.close()
        return tickers, best
    except:
        con.close()
        return [], None

# ==========================================
# 3. LAYOUT
# ==========================================
layout = dbc.Container([
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 4", className="text-muted mb-0"),
            html.H2("STRIKE SIMULATOR", className="display-6 fw-bold text-warning"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    # CONTROLS
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("1. Select Session"),
                            dcc.Dropdown(id='sim-event-selector', options=get_signal_events(), clearable=False, className="mb-2")
                        ], width=12, md=6),
                        dbc.Col([
                            html.Label("2. Select Strike"),
                            dcc.Dropdown(id='sim-strike-selector', options=[], disabled=True, clearable=False)
                        ], width=12, md=6)
                    ], className="mb-3"),

                    # PLAYBACK
                    dbc.Row([
                        dbc.Col([
                            dbc.ButtonGroup([
                                dbc.Button("▶ Play", id='sim-play-btn', color="success", outline=False),
                                dbc.Button("⏸ Pause", id='sim-pause-btn', color="warning", outline=False),
                            ], className="me-2")
                        ], width="auto"),
                        
                        dbc.Col([
                            dcc.Slider(
                                id='sim-time-slider',
                                min=0, max=390, step=1, value=0,
                                marks={0: 'Open', 60: '10:30', 195: 'Mid', 330: '15:00', 390: 'Close'},
                            )
                        ], width=True, className="align-self-center")
                    ], className="mb-2"),
                    
                    dbc.Row([
                         dbc.Col([
                            dbc.Checklist(
                                options=[{"label": " Show Algo Entry (Cheat)", "value": "SHOW"}],
                                value=[], id="sim-reveal-truth", switch=True, className="text-danger fw-bold"
                            )
                         ], width=6),
                         dbc.Col([
                             html.H4(id='sim-clock-display', children="--:-- PST", className="text-end text-primary")
                         ], width=6)
                    ])
                ])
            ], className="mb-3 shadow")
        ], width=12)
    ]),

    # CHART
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dcc.Graph(id='sim-chart', style={'height': '1000px'})
                ], className="p-1")
            ], className="shadow mb-5")
        ], width=12)
    ]),

    dcc.Interval(id='sim-auto-stepper', interval=1000, n_intervals=0, disabled=True),
    dcc.Store(id='sim-state', data={'playing': False})

], fluid=True)

# ==========================================
# 4. CALLBACKS
# ==========================================
@callback(
    [Output('sim-strike-selector', 'options'), Output('sim-strike-selector', 'value'), Output('sim-strike-selector', 'disabled')],
    [Input('sim-event-selector', 'value')]
)
def update_sim_dropdown(ts):
    if not ts: return [], None, True
    opts, best = get_tickers_for_event(ts)
    return opts, best, False

@callback(
    [Output('sim-auto-stepper', 'disabled'), Output('sim-state', 'data')],
    [Input('sim-play-btn', 'n_clicks'), Input('sim-pause-btn', 'n_clicks')],
    [State('sim-state', 'data')]
)
def toggle_simulation(play, pause, state):
    trigger = ctx.triggered_id
    if trigger == 'sim-play-btn': return False, {'playing': True}
    return True, {'playing': False}

@callback(
    Output('sim-time-slider', 'value'),
    [Input('sim-auto-stepper', 'n_intervals')],
    [State('sim-time-slider', 'value'), State('sim-time-slider', 'max')]
)
def auto_advance(n, val, max_val):
    return val + 5 if val < max_val else val

@callback(
    [Output('sim-chart', 'figure'), Output('sim-clock-display', 'children')],
    [Input('sim-event-selector', 'value'), Input('sim-strike-selector', 'value'),
     Input('sim-time-slider', 'value'), Input('sim-reveal-truth', 'value')]
)
def render_simulation(ts, ticker, mins, reveal):
    if not ts or not ticker: return go.Figure(), "--:--"

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. TIME
    try:
        trade_row = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {ts}").df().iloc[0]
        trade_date = pd.to_datetime(trade_row['date']).date()
        
        # Times in UTC for slicing
        open_pst = pd.Timestamp(f"{trade_date} 06:30:00").tz_localize(config.TZ_LOCAL)
        cutoff_utc = (open_pst + timedelta(minutes=mins)).astimezone(config.TZ_UTC)
        
        # 2. DATA LOADING
        opt_df = clean_dataframe(con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' ORDER BY datetime_utc ASC").df())
        spx_df = clean_dataframe(con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='SPX' AND CAST(datetime_utc AS DATE)='{trade_date}' ORDER BY datetime_utc ASC").df())
        
        vix_raw = clean_dataframe(con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND CAST(datetime_utc AS DATE) <= '{trade_date}' ORDER BY datetime_utc ASC").df())
        vix_raw = calculate_indicators(vix_raw, 'vix_')
        vix_today = vix_raw[vix_raw['dt'].dt.date == trade_date]
        
    except Exception as e:
        con.close()
        return go.Figure(), "Error"
    
    con.close()

    # 3. FOG OF WAR SLICE
    opt_slice = opt_df[opt_df['dt'] <= cutoff_utc]
    spx_slice = spx_df[spx_df['dt'] <= cutoff_utc]
    vix_slice = vix_today[vix_today['dt'] <= cutoff_utc]

    # 4. PLOTLY CONSTRUCTION (Matched to newplot2 style)
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        row_heights=[0.4, 0.3, 0.15, 0.15], # Proportions from Dashboard
        vertical_spacing=0.02,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: SPX (Price Action)", "Option Price (Execution)", "VIX MACD (Momentum)", "VIX RSI (Trend)")
    )

    # ROW 1: SPX (Candles)
    if not spx_slice.empty:
        fig.add_trace(go.Candlestick(
            x=spx_slice['dt'], open=spx_slice['open'], high=spx_slice['high'], low=spx_slice['low'], close=spx_slice['close'], 
            name="SPX", increasing_line_color='#26A69A', decreasing_line_color='#EF5350'
        ), row=1, col=1)

    # ROW 2: OPTION PRICE (White Line)
    if not opt_slice.empty:
        fig.add_trace(go.Scatter(
            x=opt_slice['dt'], y=opt_slice['close'], 
            mode='lines', line=dict(color='#FFFFFF', width=2), name="Option Price"
        ), row=2, col=1, secondary_y=False)
        
        # CHEAT MODE: Entry Marker
        if reveal and 'SHOW' in reveal:
             entry_dt = pd.to_datetime(ts, unit='ms', utc=True)
             if cutoff_utc >= entry_dt:
                 # Find price at entry
                 entry_price = opt_df[opt_df['dt'] >= entry_dt].iloc[0]['close']
                 fig.add_vline(x=entry_dt, line_dash="dash", line_color="#FFD600", row=2, col=1)
                 fig.add_trace(go.Scatter(
                     x=[entry_dt], y=[entry_price], mode='markers', 
                     marker=dict(color='#FFD600', size=15, symbol='triangle-up'), name="Algo Entry"
                 ), row=2, col=1)

    # ROW 3: VIX MACD (Combined)
    if not vix_slice.empty:
        # Hist Colors
        colors = ['#26A69A' if v >= 0 else '#EF5350' for v in vix_slice['vix_hist']]
        fig.add_trace(go.Bar(x=vix_slice['dt'], y=vix_slice['vix_hist'], marker_color=colors, name="Hist"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_slice['dt'], y=vix_slice['vix_macd'], line=dict(color='#2962FF', width=1.5), name="MACD"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_slice['dt'], y=vix_slice['vix_signal'], line=dict(color='#FF6D00', width=1.5), name="Signal"), row=3, col=1)

    # ROW 4: VIX RSI
    if not vix_slice.empty:
        fig.add_trace(go.Scatter(x=vix_slice['dt'], y=vix_slice['vix_rsi'], line=dict(color='#D500F9', width=2), name="RSI"), row=4, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="#EF5350", row=4, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="#26A69A", row=4, col=1)

    # STYLING
    fig.update_layout(
        template="plotly_dark", 
        height=1000, 
        showlegend=False, 
        margin=dict(t=30, b=30, l=60, r=60),
        xaxis_rangeslider_visible=False
    )
    
    # Y-Axis Labels
    fig.update_yaxes(title_text="SPX", row=1, col=1)
    fig.update_yaxes(title_text="Option $", row=2, col=1)
    fig.update_yaxes(range=[0, 100], row=4, col=1)

    # Current Sim Time
    time_str = cutoff_utc.astimezone(config.TZ_LOCAL).strftime("%H:%M PST")
    
    return fig, time_str