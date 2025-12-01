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
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# ==============================================================================
# 2. PAGE REGISTRATION
# ==============================================================================
register_page(__name__, path='/analysis', name='Analysis')
logger = get_logger("Dashboard")
STRIKE_RANGE = 2

# ==============================================================================
# 3. HELPER FUNCTIONS (The Timezone Law: Local on the Glass)
# ==============================================================================
def clean_df(df, target_timezone=config.TZ_LOCAL):
    """
    Standardizes DataFrames to Display Timezone.
    """
    if df is None or df.empty: return pd.DataFrame(columns=['dt', 'close'])
    
    # Normalize Columns
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'date': 'dt', 'timestamp': 'dt', 'close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    
    if 'dt' not in df.columns: return pd.DataFrame(columns=['dt', 'close'])

    # Ensure Datetime Type
    if not pd.api.types.is_datetime64_any_dtype(df['dt']):
        df['dt'] = pd.to_datetime(df['dt'], errors='coerce')
    
    df = df.dropna(subset=['dt'])
    
    # 1. Anchor to UTC (The Vault)
    if df['dt'].dt.tz is None:
        df['dt'] = df['dt'].dt.tz_localize(config.TZ_UTC)
    else:
        df['dt'] = df['dt'].dt.tz_convert(config.TZ_UTC)
        
    # 2. Convert to Display Timezone (The Glass)
    df['dt'] = df['dt'].dt.tz_convert(target_timezone)
    
    return df.sort_values('dt')

def calculate_indicators(df):
    if df.empty or 'close' not in df.columns: return df
    
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    # RSI
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False, min_periods=14).mean()
    ma_down = down.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def get_signal_events():
    con = duckdb.connect(str(config.DB_FILE))
    try:
        # Fetch manifest of all signals generated
        query = f"SELECT date, entry_timestamp_utc, xsp_price FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC"
        df = con.execute(query).df()
    except: return []
    con.close()
    
    # [FIX] Convert UTC Timestamp to Local Time String for Dropdown
    options = []
    for _, row in df.iterrows():
        try:
            ts_utc = pd.to_datetime(row['entry_timestamp_utc'], unit='ms', utc=True)
            ts_local = ts_utc.tz_convert(config.TZ_LOCAL)
            # Format: "2025-11-28 06:57 | Est. ATM: $682.53"
            label = f"{ts_local.strftime('%Y-%m-%d %H:%M')} | Est. ATM: ${row['xsp_price']:.2f}"
            options.append({'label': label, 'value': row['entry_timestamp_utc']})
        except:
            continue
            
    return options

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
        
        # Generate Tickers around ATM
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
# 4. LAYOUT
# ==============================================================================
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 3", className="text-muted mb-0"),
            html.H2("ANALYSIS DASHBOARD (RTH VIEW)", className="display-6 fw-bold text-dark"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("1. Signal Event"),
                            dcc.Dropdown(id='an-event-selector', options=get_signal_events(), clearable=False, className="mb-2", style={'color': '#000'})
                        ], width=6),
                        dbc.Col([
                            html.Label("2. Strike Selection"),
                            dcc.Dropdown(id='an-strike-selector', options=[], disabled=True, clearable=False, style={'color': '#000'})
                        ], width=6)
                    ])
                ])
            ], className="mb-3 shadow-sm")
        ], width=12),
        dbc.Col([html.Div(id='an-stats-panel', className="text-end text-success fw-bold mb-2")], width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([dcc.Graph(id='an-replay-chart', style={'height': '1200px'})], className="p-1")
            ], className="shadow-sm mb-5")
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

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    try:
        # Load Manifest Info
        trade_info = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {ts}").df().iloc[0]
        trade_date_str = str(pd.to_datetime(trade_info['date']).date())
        
        # --- DEFINING THE RTH WALLS (09:30 - 16:00 ET) ---
        # 1. Establish ET Walls
        tz_ny = pytz.timezone('America/New_York')
        rth_open_ny = tz_ny.localize(pd.Timestamp(f"{trade_date_str} 09:30:00"))
        rth_close_ny = tz_ny.localize(pd.Timestamp(f"{trade_date_str} 16:00:00"))
        
        # 2. Convert to Local (Glass)
        rth_open_local = rth_open_ny.astimezone(config.TZ_LOCAL)
        rth_close_local = rth_close_ny.astimezone(config.TZ_LOCAL)
        
        # --- DATA FETCHING (UTC -> Local) ---
        
        # 1. SPX (Indices)
        spx_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='SPX' AND CAST(datetime_utc AS DATE) = '{trade_date_str}' ORDER BY datetime_utc ASC").df()
        spx_df = clean_df(spx_df)
        spx_df = spx_df[(spx_df['dt'] >= rth_open_local) & (spx_df['dt'] <= rth_close_local)]

        # 2. FUTURES
        try:
            es_df = con.execute(f"SELECT * FROM {config.TBL_FUTURES} WHERE ticker='ES' AND CAST(datetime_utc AS DATE) = '{trade_date_str}' ORDER BY datetime_utc ASC").df()
            es_df = clean_df(es_df)
            es_df = es_df[(es_df['dt'] >= rth_open_local) & (es_df['dt'] <= rth_close_local)]
        except Exception:
            es_df = pd.DataFrame()

        # 3. OPTIONS
        opt_df = con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' ORDER BY datetime_utc ASC").df()
        opt_df = clean_df(opt_df)
        opt_df = opt_df[(opt_df['dt'] >= rth_open_local) & (opt_df['dt'] <= rth_close_local)]
        
        # 4. VIX Indicators
        start_date = str(pd.to_datetime(trade_date_str) - timedelta(days=60))
        vix_raw = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND CAST(datetime_utc AS DATE) BETWEEN '{start_date}' AND '{trade_date_str}' ORDER BY datetime_utc ASC").df()
        vix_raw = clean_df(vix_raw)
        vix_raw = calculate_indicators(vix_raw)
        
        vix_plot = vix_raw[vix_raw['dt'].dt.date == pd.to_datetime(trade_date_str).date()].copy()
        vix_plot = vix_plot[(vix_plot['dt'] >= rth_open_local) & (vix_plot['dt'] <= rth_close_local)]
        
    except Exception as e:
        con.close()
        logger.error(f"Dashboard Data Error: {e}")
        return go.Figure(), f"Error: {str(e)}"
    
    con.close()

    # --- ANALYTICS (Entry & Max Gain) ---
    signal_dt_utc = pd.to_datetime(ts, unit='ms', utc=True)
    signal_dt_local = signal_dt_utc.tz_convert(config.TZ_LOCAL)
    
    entry_price = 0
    entry_time = None
    max_gain_price = 0
    max_gain_time = None
    max_gain_pct = 0
    
    if not opt_df.empty:
        # 1. Identify Entry
        entry_slice = opt_df[opt_df['dt'] >= signal_dt_local]
        
        if not entry_slice.empty:
            entry_row = entry_slice.iloc[0]
            entry_price = entry_row['close']
            entry_time = entry_row['dt']
            
            # 2. Identify Max Gain (Peak High AFTER entry)
            # Filter for trade window (Entry -> Close)
            trade_window = entry_slice.copy()
            if not trade_window.empty:
                max_idx = trade_window['high'].idxmax()
                max_gain_price = trade_window.loc[max_idx, 'high']
                max_gain_time = trade_window.loc[max_idx, 'dt']
                max_gain_pct = ((max_gain_price - entry_price) / entry_price) * 100

            # P&L Vector for Chart
            opt_df['P&L_Pct'] = ((opt_df['close'] - entry_price) / entry_price) * 100
            # Light Mode colors: Green/Red transparency
            opt_df['P&L_Color'] = np.where(opt_df['P&L_Pct'] >= 0, 'rgba(0, 200, 83, 0.3)', 'rgba(213, 0, 0, 0.3)')
            
            stats_text = f"ENTRY: ${entry_price:.2f} | PEAK: ${max_gain_price:.2f} (+{max_gain_pct:.1f}%)"
        else:
            stats_text = "Signal outside RTH Data range"
    else:
        stats_text = "No Option Data"

    # --- PLOTTING ---
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        row_heights=[0.4, 0.3, 0.15, 0.15], 
        vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: SPX (Hollow) vs /ES (Line)", "Strategy: Option Price vs P&L Overlay", "VIX MACD", "VIX RSI")
    )

    # 1. Context
    if not spx_df.empty:
        fig.add_trace(go.Candlestick(
            x=spx_df['dt'], 
            open=spx_df['open'], high=spx_df['high'], low=spx_df['low'], close=spx_df['close'], 
            name="SPX",
            increasing_line_color='#2E7D32', increasing_fillcolor='rgba(0,0,0,0)', # Hollow Green
            decreasing_line_color='#C62828', decreasing_fillcolor='#C62828'   # Filled Red
        ), row=1, col=1)
    
    if not es_df.empty:
        fig.add_trace(go.Scatter(
            x=es_df['dt'], y=es_df['close'], 
            mode='lines', 
            line=dict(color='#0277BD', width=1, dash='dot'), # Blue Dashed
            name="/ES Futures"
        ), row=1, col=1)

    # 2. Options P&L
    if not opt_df.empty:
        # P&L Bars (Background)
        fig.add_trace(go.Bar(
            x=opt_df['dt'], y=opt_df['P&L_Pct'], 
            marker_color=opt_df['P&L_Color'], 
            name="P&L %", opacity=0.5
        ), row=2, col=1, secondary_y=True)
        
        # Price Line (Foreground)
        fig.add_trace(go.Scatter(
            x=opt_df['dt'], y=opt_df['close'], 
            mode='lines', 
            line=dict(color='#2962FF', width=2), 
            name="Option Price"
        ), row=2, col=1, secondary_y=False)
        
        # ENTRY MARKER
        if entry_price > 0 and entry_time is not None:
            fig.add_vline(x=entry_time, line_dash="dash", line_color="#2962FF", row=2, col=1)
            fig.add_trace(go.Scatter(
                x=[entry_time], y=[entry_price],
                mode='markers', marker=dict(color='#2962FF', size=12, symbol='triangle-up'),
                name="Entry"
            ), row=2, col=1, secondary_y=False)

        # MAX GAIN MARKER (The "Star")
        if max_gain_time is not None:
            fig.add_trace(go.Scatter(
                x=[max_gain_time], y=[max_gain_price],
                mode='markers+text', 
                marker=dict(color='#00C853', size=14, symbol='star'),
                text=[f"+{max_gain_pct:.1f}%"], textposition="top center",
                textfont=dict(color='#00C853', weight='bold'),
                name=f"Max (+{max_gain_pct:.0f}%)"
            ), row=2, col=1, secondary_y=False)

    # 3. VIX Indicators
    if not vix_plot.empty:
        colors = ['#66BB6A' if v >= 0 else '#EF5350' for v in vix_plot['hist']]
        fig.add_trace(go.Bar(x=vix_plot['dt'], y=vix_plot['hist'], marker_color=colors, name="Hist"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['macd'], line=dict(color='#B2FF59', width=1.5), name="MACD"), row=3, col=1) # Light Green
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['signal'], line=dict(color='#FF80AB', width=1.5), name="Sig"), row=3, col=1) # Pink
        
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['rsi'], line=dict(color='#7E57C2', width=2), name="RSI"), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#C62828", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#2E7D32", row=4, col=1)

    fig.update_layout(
        template="plotly_white", 
        height=1200, 
        xaxis_rangeslider_visible=False, 
        margin=dict(t=50, b=50, l=60, r=60),
        legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center") # Bottom Legend
    )
    
    # Axis styling
    fig.update_yaxes(gridcolor='#F5F5F5')
    fig.update_xaxes(gridcolor='#F5F5F5')

    return fig, stats_text