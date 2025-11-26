import sys
import os
import dash
from dash import dcc, html, Input, Output, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import duckdb
import pandas as pd
import numpy as np
import logging
from datetime import timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# We are in: quant-trading-pipeline/src/tools/
# We need to reach: quant-trading-pipeline/ (Root)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Add Root to System Path to allow imports from 'src.utils'
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# ==============================================================================
# 2. SETUP
# ==============================================================================
register_page(__name__, path='/analysis', name='Analysis')

logger = logging.getLogger("Dashboard")
UTC_TZ = pytz.utc
STRIKE_RANGE = 2

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def clean_df(df):
    """
    Standardizes DataFrames for display.
    ENFORCES TIMEZONE LAW: Converts UTC Storage -> Local Display (PST).
    """
    if df.empty: return df
    
    # Normalize Columns
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'date': 'dt', 'timestamp': 'dt', 'close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    
    if 'dt' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['dt']):
            df['dt'] = pd.to_datetime(df['dt'])
        
        # 1. Ensure UTC Awareness (Vault Standard)
        if df['dt'].dt.tz is None:
            df['dt'] = df['dt'].dt.tz_localize(UTC_TZ)
        else:
            df['dt'] = df['dt'].dt.tz_convert(UTC_TZ)
            
        # 2. TIMEZONE LAW: CONVERT TO LOCAL FOR DISPLAY ("Local on the Glass")
        df['dt'] = df['dt'].dt.tz_convert(config.TZ_LOCAL)
            
        df = df.drop_duplicates(subset=['dt'])
    return df

def calculate_indicators(df):
    if 'close' not in df.columns: return df
    
    # MACD (12, 26, 9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    # RSI (Wilder's 14)
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False, min_periods=14).mean()
    ma_down = down.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi_ma'] = df['rsi'].rolling(window=14).mean()
    
    return df

def get_signal_events():
    con = duckdb.connect(str(config.DB_FILE))
    try:
        # Sort by latest signals
        query = f"SELECT date, entry_timestamp_utc, xsp_price FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC"
        df = con.execute(query).df()
    except Exception: return []
    con.close()
    
    # We display the UTC Date, but the ID is the timestamp
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
            label = f"{ticker} ({'ATM' if offset==0 else 'OTM' if offset>0 else 'ITM'} ${strike})"
            tickers.append({'label': label, 'value': ticker})
            if offset == 0: best = ticker
            
        con.close()
        return tickers, best
    except:
        con.close()
        return [], None

# ==============================================================================
# 4. LAYOUT (Unified Design System)
# ==============================================================================
layout = dbc.Container([
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 3", className="text-muted mb-0"),
            html.H2("ANALYSIS DASHBOARD", className="display-6 fw-bold text-info"),
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
                            html.Label("1. Signal Event"),
                            dcc.Dropdown(id='an-event-selector', options=get_signal_events(), clearable=False, className="mb-2")
                        ], width=12, md=6),
                        dbc.Col([
                            html.Label("2. Strike Selection"),
                            dcc.Dropdown(id='an-strike-selector', options=[], disabled=True, clearable=False)
                        ], width=12, md=6)
                    ])
                ])
            ], className="mb-3 shadow")
        ], width=12),
        
        # STATS PANEL
        dbc.Col([
            html.Div(id='an-stats-panel', className="text-end text-info fw-bold mb-2")
        ], width=12)
    ]),

    # GRAPH
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dcc.Graph(id='an-replay-chart', style={'height': '1200px'})
                ], className="p-1") 
            ], className="shadow mb-5")
        ], width=12)
    ])

], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    [Output('an-strike-selector', 'options'), Output('an-strike-selector', 'value'), Output('an-strike-selector', 'disabled')],
    [Input('an-event-selector', 'value')]
)
def update_dropdown(ts):
    if not ts: return [], None, True
    options, best = get_tickers_for_event(ts)
    return options, best, False

@callback(
    [Output('an-replay-chart', 'figure'), Output('an-stats-panel', 'children')],
    [Input('an-event-selector', 'value'), Input('an-strike-selector', 'value')]
)
def update_chart(ts, ticker):
    if not ts or not ticker: return go.Figure(), ""

    con = duckdb.connect(str(config.DB_FILE))
    
    # --- DATA LOADING ---
    try:
        trade_info = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {ts}").df().iloc[0]
        trade_date = pd.to_datetime(trade_info['date']).date()
        
        # SPX
        spx_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='SPX' AND CAST(datetime_utc AS DATE) = '{trade_date}' ORDER BY datetime_utc ASC").df()
        spx_df = clean_df(spx_df)
        
        # Futures (Optional)
        try:
            es_df = con.execute(f"SELECT * FROM {config.TBL_FUTURES} WHERE ticker='ES' AND CAST(datetime_utc AS DATE) = '{trade_date}' ORDER BY datetime_utc ASC").df()
            es_df = clean_df(es_df)
        except: es_df = pd.DataFrame()

        # Options
        opt_df = con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' ORDER BY datetime_utc ASC").df()
        opt_df = clean_df(opt_df)
        
        # VIX Indicators (60 day lookback)
        start_date = str(trade_date - timedelta(days=60))
        vix_raw = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND CAST(datetime_utc AS DATE) BETWEEN '{start_date}' AND '{trade_date}' ORDER BY datetime_utc ASC").df()
        vix_raw = clean_df(vix_raw)
        vix_raw = calculate_indicators(vix_raw)
        # Filter strictly for display date after calculation
        vix_plot = vix_raw[vix_raw['dt'].dt.date == trade_date].copy()
        
    except Exception as e:
        con.close()
        return go.Figure(), f"Error: {str(e)}"
    
    con.close()

    if opt_df.empty: return go.Figure(), "No Option Data Found"

    # --- ENTRY & P&L LOGIC ---
    # Signal Timestamp is UTC. We need to convert to Local for comparison because clean_df converted DFs to Local.
    signal_dt_utc = pd.to_datetime(ts, unit='ms', utc=True)
    signal_dt_local = signal_dt_utc.tz_convert(config.TZ_LOCAL)
    
    entry_slice = opt_df[opt_df['dt'] >= signal_dt_local]
    
    if not entry_slice.empty:
        entry_row = entry_slice.iloc[0]
        entry_price = entry_row['close']
        entry_time = entry_row['dt']
        
        opt_df['P&L_Pct'] = ((opt_df['close'] - entry_price) / entry_price) * 100
        opt_df['P&L_Color'] = np.where(opt_df['P&L_Pct'] >= 0, 'rgba(0, 200, 83, 0.7)', 'rgba(211, 47, 47, 0.7)')
        
        max_roi = opt_df[opt_df['dt'] >= entry_time]['P&L_Pct'].max()
        stats_text = f"ENTRY: ${entry_price:.2f} | PEAK ROI: +{max_roi:.1f}%"
    else:
        entry_price = 0
        stats_text = "Signal Mismatch (No overlapping option data)"

    # --- PLOTTING ---
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        row_heights=[0.4, 0.3, 0.15, 0.15], 
        vertical_spacing=0.03,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: SPX vs /ES Futures (Local Time)", "Strategy: Option Price vs P&L", "VIX MACD (Momentum)", "VIX RSI (Trend)")
    )

    # ROW 1: SPX & FUTURES
    fig.add_trace(go.Candlestick(
        x=spx_df['dt'], open=spx_df['open'], high=spx_df['high'], low=spx_df['low'], close=spx_df['close'], 
        name="SPX", increasing_line_color='#26A69A', decreasing_line_color='#EF5350'
    ), row=1, col=1)
    
    if not es_df.empty:
        fig.add_trace(go.Scatter(x=es_df['dt'], y=es_df['close'], mode='lines', name="/ES Futures", line=dict(color='#2962FF', width=1, dash='dot'), opacity=0.7), row=1, col=1)

    # ROW 2: OPTION P&L
    fig.add_trace(go.Bar(x=opt_df['dt'], y=opt_df['P&L_Pct'], marker_color=opt_df['P&L_Color'], name="P&L %", hoverinfo='y'), row=2, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=opt_df['dt'], y=opt_df['close'], mode='lines', line=dict(color='#FFFFFF', width=2), name="Option Price"), row=2, col=1, secondary_y=False)
    
    if entry_price > 0:
        fig.add_vline(x=entry_time, line_dash="dash", line_color="#FFD600", opacity=0.8, row=2, col=1)

    # ROW 3: VIX MACD
    if not vix_plot.empty:
        vix_plot['hist_prev'] = vix_plot['hist'].shift(1)
        colors = ['#26A69A' if v >= 0 else '#EF5350' for v in vix_plot['hist']] 
        
        fig.add_trace(go.Bar(x=vix_plot['dt'], y=vix_plot['hist'], name="Hist", marker_color=colors), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['macd'], name="MACD", line=dict(color='#2962FF', width=1.5)), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['signal'], name="Signal", line=dict(color='#FF6D00', width=1.5)), row=3, col=1)

    # ROW 4: VIX RSI
    if not vix_plot.empty:
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['rsi'], name="RSI", line=dict(color='#D500F9', width=2)), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#EF5350", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#26A69A", row=4, col=1)

    # STYLING
    fig.update_layout(
        template="plotly_dark", 
        height=1200, 
        showlegend=True, 
        xaxis_rangeslider_visible=False,
        margin=dict(t=30, b=30, l=60, r=60),
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center")
    )
    
    fig.update_yaxes(title_text="Price", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="P&L %", row=2, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(range=[0, 100], row=4, col=1)

    return fig, stats_text