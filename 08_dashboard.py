import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import duckdb
import pandas as pd
import numpy as np
import sys
import pytz
import logging
from datetime import timedelta, datetime
from pathlib import Path

# ==========================================
# 0. GLOBAL PATH SETUP
# ==========================================
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent
sys.path.append(str(project_root))
sys.path.append(str(current_file.parent))

# Logger Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dashboard")

try:
    from src.utils import config
except ImportError:
    class Config:
        DB_FILE = 'market_data/quant_strategy.duckdb'
        TZ_LOCAL = pytz.timezone('US/Pacific')
        TZ_UTC = pytz.utc
        TBL_MANIFEST = 'trade_manifest'
        TBL_INDICES = 'indices_1m'
        TBL_OPTIONS = 'options_1m'
        TBL_FUTURES = 'futures_1m'
    config = Config()

# ==========================================
# 1. CONFIGURATION
# ==========================================
app = dash.Dash(__name__, title="Confluence Deck (v2.8 Final)")
PST_TZ = config.TZ_LOCAL
UTC_TZ = config.TZ_UTC
STRIKE_RANGE = 2

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def get_signal_events():
    con = duckdb.connect(str(config.DB_FILE))
    try:
        query = f"SELECT date, entry_timestamp_utc, xsp_price FROM {config.TBL_MANIFEST} ORDER BY date DESC"
        df = con.execute(query).df()
    except Exception as e:
        logger.error(f"Manifest Error: {e}")
        return []
    con.close()
    
    options = []
    for _, row in df.iterrows():
        label = f"{row['date']} | Est. ATM: ${row['xsp_price']:.2f}"
        options.append({'label': label, 'value': row['entry_timestamp_utc']})
    return options

def get_tickers_for_event(con, event_timestamp_utc):
    if not event_timestamp_utc: return [], None
    try:
        event_row = con.execute(f"SELECT date, xsp_price FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_timestamp_utc}").df().iloc[0]
    except: return [], None

    trade_date = pd.to_datetime(event_row['date'])
    date_str = trade_date.strftime("%y%m%d")
    target_price = event_row['xsp_price']
    atm_strike = round(target_price)
    
    tickers = []
    best_ticker = None
    
    for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
        strike = atm_strike + offset
        strike_str = f"{int(strike * 1000):08d}"
        ticker = f"O:XSP{date_str}C{strike_str}"
        
        label_type = "ATM" if offset == 0 else ("ITM" if offset < 0 else "OTM")
        label = f"{ticker} ({label_type} ${strike})"
        
        tickers.append({'label': label, 'value': ticker})
        if offset == 0: best_ticker = ticker
        
    return tickers, best_ticker

def clean_df(df):
    if df.empty: return df
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'date': 'dt', 'timestamp': 'dt', 'close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    
    if 'dt' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['dt']):
            df['dt'] = pd.to_datetime(df['dt'])
        
        # Enforce UTC Awareness
        if df['dt'].dt.tz is None:
            df['dt'] = df['dt'].dt.tz_localize(UTC_TZ)
        else:
            df['dt'] = df['dt'].dt.tz_convert(UTC_TZ)
            
        df = df.drop_duplicates(subset=['dt'])
        
    return df

def calculate_indicators(df):
    if 'close' not in df.columns: return df
    
    # MACD (Standard 12/26/9)
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
    
    # RSI MA (Yellow Line)
    df['rsi_ma'] = df['rsi'].rolling(window=14).mean()
    
    return df

# ==========================================
# 3. LAYOUT
# ==========================================
signal_events = get_signal_events()

app.layout = html.Div([
    # Header
    html.Div([
        html.H1("💎 Confluence Deck v2.8", style={'margin': '0', 'color': '#333', 'fontSize': '24px'}),
        html.P("Professional Layout (Right-Side Legend)", style={'margin': '0', 'color': '#666', 'fontSize': '14px'})
    ], style={'backgroundColor': '#fff', 'padding': '15px', 'fontFamily': 'sans-serif', 'borderBottom': '1px solid #eee', 'marginBottom': '20px'}),

    # Controls
    html.Div([
        html.Div([
            html.Label("Select Signal Event:", style={'fontWeight': 'bold', 'color': '#333'}),
            dcc.Dropdown(id='event-selector', options=signal_events, value=signal_events[0]['value'] if signal_events else None, clearable=False, style={'color': '#333'})
        ], style={'width': '40%', 'display': 'inline-block', 'paddingRight': '20px', 'verticalAlign': 'top'}),
        
        html.Div([
            html.Label("Select Strike:", style={'fontWeight': 'bold', 'color': '#333'}),
            dcc.Dropdown(id='strike-selector', options=[], disabled=False, clearable=False, style={'color': '#333'})
        ], style={'width': '40%', 'display': 'inline-block', 'verticalAlign': 'top'}),
        
        html.Div(id='stats-panel', style={'width': '15%', 'display': 'inline-block', 'float': 'right', 'textAlign': 'right', 'fontWeight': 'bold', 'color': '#2962FF', 'paddingTop': '25px'})
    ], style={'padding': '20px', 'backgroundColor': '#f9f9f9', 'borderBottom': '1px solid #ddd'}),

    dcc.Graph(id='replay-chart', style={'height': '1300px'}),
], style={'backgroundColor': 'white'})

# ==========================================
# 4. CALLBACKS
# ==========================================
@app.callback(
    [Output('strike-selector', 'options'), Output('strike-selector', 'value')],
    [Input('event-selector', 'value')]
)
def update_strike_dropdown(selected_event_ts):
    if not selected_event_ts: return [], None
    con = duckdb.connect(str(config.DB_FILE))
    options, best = get_tickers_for_event(con, selected_event_ts)
    con.close()
    return options, best

@app.callback(
    [Output('replay-chart', 'figure'), Output('stats-panel', 'children')],
    [Input('event-selector', 'value'), Input('strike-selector', 'value')]
)
def update_chart(event_timestamp_utc, selected_ticker):
    if not event_timestamp_utc or not selected_ticker: return go.Figure(), ""

    con = duckdb.connect(str(config.DB_FILE))
    trade_info = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_timestamp_utc}").df().iloc[0]
    trade_date = pd.to_datetime(trade_info['date']).date()
    
    # Load Data
    spx_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='SPX' AND CAST(datetime_utc AS DATE) = '{trade_date}' ORDER BY datetime_utc ASC").df()
    spx_df = clean_df(spx_df)
    
    try:
        es_df = con.execute(f"SELECT * FROM {config.TBL_FUTURES} WHERE ticker='ES' AND CAST(datetime_utc AS DATE) = '{trade_date}' ORDER BY datetime_utc ASC").df()
        es_df = clean_df(es_df)
    except: es_df = pd.DataFrame()

    opt_df = con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker='{selected_ticker}' ORDER BY datetime_utc ASC").df()
    opt_df = clean_df(opt_df)
    
    start_date = str(trade_date - timedelta(days=60))
    vix_raw = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND CAST(datetime_utc AS DATE) BETWEEN '{start_date}' AND '{trade_date}' ORDER BY datetime_utc ASC").df()
    vix_raw = clean_df(vix_raw)
    vix_raw = calculate_indicators(vix_raw)
    vix_plot = vix_raw[vix_raw['dt'].dt.date == trade_date].copy()
    
    con.close()
    
    if opt_df.empty: return go.Figure(), "No Option Data"

    # Entry Logic
    signal_dt = pd.to_datetime(event_timestamp_utc, unit='ms', utc=True)
    entry_slice = opt_df[opt_df['dt'] >= signal_dt]
    
    if not entry_slice.empty:
        entry_row = entry_slice.iloc[0]
        entry_price = entry_row['close']
        entry_time = entry_row['dt']
        
        # P&L (Darker Opacity 0.7)
        opt_df['P&L_Pct'] = ((opt_df['close'] - entry_price) / entry_price) * 100
        opt_df['P&L_Color'] = np.where(opt_df['P&L_Pct'] >= 0, 'rgba(0, 200, 83, 0.7)', 'rgba(211, 47, 47, 0.7)')
        
        post_entry = opt_df[opt_df['dt'] >= entry_time]
        max_roi = post_entry['P&L_Pct'].max() if not post_entry.empty else 0.0
        stats_text = f"Entry: ${entry_price:.2f} | Max ROI: +{max_roi:.1f}%"
    else:
        entry_price, entry_time = 0, opt_df.iloc[0]['dt']
        opt_df['P&L_Pct'] = 0
        opt_df['P&L_Color'] = 'grey'
        stats_text = "Signal Mismatch"

    # --- STYLING LOGIC ---
    if not vix_plot.empty:
        vix_plot['hist_prev'] = vix_plot['hist'].shift(1)
        def get_hist_color(row):
            val, prev = row['hist'], row['hist_prev']
            if pd.isna(prev): return 'gray'
            if val >= 0: return '#26A69A' if val >= prev else '#B2DFDB' 
            else: return '#EF5350' if val <= prev else '#FFCDD2'
        hist_colors = vix_plot.apply(get_hist_color, axis=1)
        
        # RSI Histogram (Red/Green Momentum Fill)
        vix_plot['rsi_color'] = np.where(vix_plot['rsi'] >= 50, 'rgba(38, 166, 154, 0.3)', 'rgba(239, 83, 80, 0.3)')

    # --- PLOTTING ---
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        row_heights=[0.4, 0.3, 0.15, 0.15], 
        vertical_spacing=0.05,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: SPX vs /ES Futures", "Strategy: Option Price vs P&L", "VIX MACD", "VIX RSI")
    )

    # ROW 1: SPX & FUTURES
    fig.add_trace(go.Candlestick(
        x=spx_df['dt'], open=spx_df['open'], high=spx_df['high'], low=spx_df['low'], close=spx_df['close'], 
        name="SPX", increasing_line_color='#26A69A', decreasing_line_color='#EF5350'
    ), row=1, col=1)
    
    if not es_df.empty:
        fig.add_trace(go.Scatter(x=es_df['dt'], y=es_df['close'], mode='lines', name="/ES Futures", line=dict(color='#2962FF', width=1.5, dash='dot'), opacity=0.6), row=1, col=1)

    # ROW 2: Option Price
    fig.add_trace(go.Bar(x=opt_df['dt'], y=opt_df['P&L_Pct'], marker_color=opt_df['P&L_Color'], name="P&L %", hoverinfo='y'), row=2, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=opt_df['dt'], y=opt_df['close'], mode='lines', line=dict(color='#2962FF', width=2), name="Option Price"), row=2, col=1, secondary_y=False)
    
    if entry_price > 0:
        fig.add_trace(go.Scatter(x=[entry_time], y=[entry_price], mode='markers', marker=dict(color='#FFD600', size=14, symbol='triangle-up', line=dict(width=2, color='black')), name="Entry"), row=2, col=1, secondary_y=False)
        fig.add_vline(x=entry_time, line_dash="dash", line_color="#2962FF", opacity=0.5, row=2, col=1)

    # ROW 3: MACD
    if not vix_plot.empty:
        fig.add_trace(go.Bar(x=vix_plot['dt'], y=vix_plot['hist'], name="Hist", marker_color=hist_colors), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['macd'], name="MACD", line=dict(color='#2962FF', width=1.5)), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['signal'], name="Signal", line=dict(color='#FF6D00', width=1.5)), row=3, col=1)

    # ROW 4: RSI (TV Style)
    if not vix_plot.empty:
        # RSI Histogram (Fill relative to 50)
        fig.add_trace(go.Bar(x=vix_plot['dt'], y=vix_plot['rsi']-50, base=50, name="Momentum", marker_color=vix_plot['rsi_color']), row=4, col=1)
        
        # RSI MA (Yellow)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['rsi_ma'], name="RSI MA", line=dict(color='#FFEB3B', width=1.5)), row=4, col=1)
        
        # RSI Line (Purple)
        fig.add_trace(go.Scatter(x=vix_plot['dt'], y=vix_plot['rsi'], name="RSI", line=dict(color='#7E57C2', width=2)), row=4, col=1)
        
        fig.add_hline(y=70, line_dash="dash", line_color="#B0B0B0", row=4, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#B0B0B0", row=4, col=1)

    # FIX: Move Legend to Right Side Vertical
    fig.update_layout(
        template="plotly_white", 
        height=1300, 
        showlegend=True, 
        xaxis_rangeslider_visible=False,
        margin=dict(t=60, b=60, l=60, r=60),
        legend=dict(orientation="v", y=1, x=1.02, xanchor="left", bgcolor='rgba(255,255,255,0.8)')
    )
    
    # Fix Y-Axes Scaling
    fig.update_yaxes(title_text="Price ($)", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="P&L (%)", row=2, col=1, secondary_y=True, showgrid=False)
    fig.update_yaxes(range=[0, 100], row=4, col=1) # Lock RSI
    
    return fig, stats_text

if __name__ == '__main__':
    app.run(debug=True, port=8050)