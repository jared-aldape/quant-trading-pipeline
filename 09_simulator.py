import dash
from dash import dcc, html, Input, Output, State, ctx
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
# 0. GLOBAL PATH & LOGGING SETUP
# ==========================================
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent
sys.path.append(str(project_root))
sys.path.append(str(current_file.parent)) 

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SimPilot")

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
    config = Config()

# ==========================================
# 1. CONFIGURATION
# ==========================================
app = dash.Dash(__name__, title="Strike Simulator (v2.9 UX)")
PST_TZ = config.TZ_LOCAL
UTC_TZ = config.TZ_UTC
STRIKE_RANGE = 2

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def get_signal_events():
    con = duckdb.connect(str(config.DB_FILE))
    try:
        # Get signals and the estimated XSP price stored in manifest
        query = f"SELECT date, entry_timestamp_utc, xsp_price FROM {config.TBL_MANIFEST} ORDER BY date DESC"
        df = con.execute(query).df()
    except Exception as e:
        logger.error(f"Manifest Load Error: {e}")
        return []
    con.close()
    
    options = []
    for _, row in df.iterrows():
        label = f"{row['date']} | Est. ATM: ${row['xsp_price']:.2f}"
        options.append({'label': label, 'value': row['entry_timestamp_utc']})
    return options

def get_tickers_for_event(con, event_timestamp_utc):
    """
    Returns list of tickers, identifying the ATM one.
    """
    if not event_timestamp_utc: return [], None
    
    try:
        # Get the Target Price from Manifest
        event_row = con.execute(f"SELECT date, xsp_price FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_timestamp_utc}").df().iloc[0]
        target_price = event_row['xsp_price']
    except: 
        return [], None

    trade_date = pd.to_datetime(event_row['date'])
    date_str = trade_date.strftime("%y%m%d")
    
    # Generate Tickers
    tickers = []
    atm_strike = round(target_price)
    best_ticker = None
    min_diff = 9999
    
    # We search the DB for available tickers that match this pattern
    # This handles cases where we fetched ATM-2 to ATM+2
    try:
        # Look for tickers in DB that match the date pattern
        # Efficient regex search or just generate range
        available_tickers = []
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
            strike = atm_strike + offset
            strike_str = f"{int(strike * 1000):08d}"
            ticker = f"O:XSP{date_str}C{strike_str}"
            
            # Label ITM/ATM/OTM
            label_type = "ATM" if offset == 0 else ("ITM" if offset < 0 else "OTM")
            label = f"{ticker} ({label_type} ${strike})"
            
            tickers.append({'label': label, 'value': ticker})
            
            if offset == 0:
                best_ticker = ticker
                
    except Exception as e:
        logger.error(f"Ticker Gen Error: {e}")
        return [], None
        
    return tickers, best_ticker

def clean_dataframe(df, name="DF"):
    if df.empty: 
        logger.warning(f"{name} is EMPTY during cleaning.")
        return df
    
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()] 
    
    rename_map = {
        'datetime_utc': 'dt', 
        'datetime': 'dt', 
        'date': 'dt', 
        'timestamp': 'dt', 
        'close': 'close', 
        'vix_close': 'close'
    }
    df.rename(columns=rename_map, inplace=True)
    
    if 'dt' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['dt']):
            df['dt'] = pd.to_datetime(df['dt'])
        
        if df['dt'].dt.tz is None:
            df['dt'] = df['dt'].dt.tz_localize(UTC_TZ)
        else:
            df['dt'] = df['dt'].dt.tz_convert(UTC_TZ)
            
        # Deduplicate
        df = df.drop_duplicates(subset=['dt'])
    else:
        logger.error(f"{name} missing 'dt' column!")
            
    return df

def calculate_indicators(df, prefix=''):
    if 'close' not in df.columns: return df

    # MACD
    df[f'{prefix}EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
    df[f'{prefix}EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df[f'{prefix}MACD'] = df[f'{prefix}EMA12'] - df[f'{prefix}EMA26']
    df[f'{prefix}Signal'] = df[f'{prefix}MACD'].ewm(span=9, adjust=False).mean()
    df[f'{prefix}Histogram'] = df[f'{prefix}MACD'] - df[f'{prefix}Signal']
    
    # RSI (Wilder's Smoothing for smoothness)
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False, min_periods=14).mean()
    ma_down = down.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = ma_up / ma_down
    df[f'{prefix}RSI'] = 100 - (100 / (1 + rs))
    
    return df

# ==========================================
# 3. LAYOUT
# ==========================================
signal_events = get_signal_events()

app.layout = html.Div([
    html.Div([
        html.H1("🎯 Strike Simulator v2.9", style={'margin': '0', 'color': 'white', 'fontSize': '24px'}),
        html.P("Auto-ATM Selection & Gap Bridging.", style={'margin': '0', 'color': '#aaa', 'fontSize': '14px'})
    ], style={'backgroundColor': '#1a1a1a', 'padding': '15px', 'fontFamily': 'sans-serif'}),

    html.Div([
        html.Div([
            html.Label("1. Session:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='event-selector', options=signal_events, value=signal_events[0]['value'] if signal_events else None, clearable=False),
            html.Label("2. Strike (Auto-Selected ATM):", style={'fontWeight': 'bold', 'marginTop': '10px'}),
            dcc.Dropdown(id='strike-selector', options=[], disabled=False, clearable=False)
        ], style={'width': '25%', 'display': 'inline-block', 'verticalAlign': 'top', 'paddingRight': '20px'}),

        html.Div([
            html.Div([
                html.Button('▶ Play', id='play-btn', n_clicks=0, style={'backgroundColor': '#4CAF50', 'color': 'white', 'border': 'none', 'padding': '8px 15px', 'marginRight': '10px', 'cursor': 'pointer'}),
                html.Button('⏸ Pause', id='pause-btn', n_clicks=0, style={'backgroundColor': '#FF9800', 'color': 'white', 'border': 'none', 'padding': '8px 15px', 'marginRight': '10px', 'cursor': 'pointer'}),
                dcc.Checklist(
                    id='reveal-truth',
                    options=[{'label': ' 👁️ REVEAL ENTRY', 'value': 'SHOW'}],
                    value=[],
                    style={'display': 'inline-block', 'fontWeight': 'bold', 'color': '#D32F2F', 'marginLeft': '20px'}
                )
            ], style={'marginBottom': '10px'}),
            
            dcc.Slider(
                id='time-slider',
                min=0, max=390, step=1, 
                value=0,
                marks={0: '06:30', 60: '07:30', 120: '08:30', 180: '09:30', 240: '10:30', 300: '11:30', 390: '13:00'},
            ),
            html.Div(id='current-sim-time', style={'textAlign': 'center', 'fontWeight': 'bold', 'color': '#2962FF'})

        ], style={'width': '70%', 'display': 'inline-block', 'verticalAlign': 'top', 'backgroundColor': '#f5f5f5', 'padding': '15px', 'borderRadius': '8px'})
    ], style={'padding': '20px', 'borderBottom': '1px solid #ddd'}),

    dcc.Graph(id='sim-chart', style={'height': '1200px'}),
    dcc.Interval(id='auto-stepper', interval=1000, n_intervals=0, disabled=True),
    dcc.Store(id='sim-state', data={'playing': False})
])

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
    options, best_ticker = get_tickers_for_event(con, selected_event_ts)
    con.close()
    
    # Auto-select the ATM (best_ticker)
    return options, best_ticker

@app.callback(
    [Output('auto-stepper', 'disabled'), Output('sim-state', 'data')],
    [Input('play-btn', 'n_clicks'), Input('pause-btn', 'n_clicks')],
    [State('sim-state', 'data')]
)
def toggle_simulation(play_clicks, pause_clicks, state):
    trigger = ctx.triggered_id
    if trigger == 'play-btn': return False, {'playing': True}
    if trigger == 'pause-btn': return True, {'playing': False}
    return True, {'playing': False}

@app.callback(
    Output('time-slider', 'value'),
    [Input('auto-stepper', 'n_intervals')],
    [State('time-slider', 'value'), State('time-slider', 'max')]
)
def advance_slider(n, current_val, max_val):
    if current_val < max_val: return current_val + 5
    return current_val

@app.callback(
    [Output('sim-chart', 'figure'), Output('current-sim-time', 'children')],
    [Input('event-selector', 'value'), 
     Input('strike-selector', 'value'),
     Input('time-slider', 'value'),
     Input('reveal-truth', 'value')]
)
def update_simulation(event_timestamp_utc, selected_ticker, slider_minutes, reveal_truth):
    if not event_timestamp_utc or not selected_ticker: 
        return go.Figure(), "Waiting..."

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. TIME ANCHORS
    trade_row = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_timestamp_utc}").df().iloc[0]
    trade_date = pd.to_datetime(trade_row['date']).date()
    
    market_open_pst = pd.Timestamp(f"{trade_date} 06:30:00").tz_localize(PST_TZ)
    market_close_pst = pd.Timestamp(f"{trade_date} 13:00:00").tz_localize(PST_TZ)
    market_open_utc = market_open_pst.astimezone(UTC_TZ)
    market_close_utc = market_close_pst.astimezone(UTC_TZ)
    
    cutoff_utc = market_open_utc + timedelta(minutes=slider_minutes)
    
    # 2. DATA LOADING
    try:
        opt_df = con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker = '{selected_ticker}' ORDER BY datetime_utc ASC").df()
        opt_df = clean_dataframe(opt_df, "OPT")
    except Exception: opt_df = pd.DataFrame()

    try:
        spx_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker = 'SPX' AND CAST(datetime_utc AS DATE) = '{trade_date}' ORDER BY datetime_utc ASC").df()
        spx_df = clean_dataframe(spx_df, "SPX")
    except Exception: spx_df = pd.DataFrame()

    try:
        start_date_str = str(trade_date - timedelta(days=60))
        vix_raw = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker = 'VIX' AND CAST(datetime_utc AS DATE) BETWEEN '{start_date_str}' AND '{trade_date}' ORDER BY datetime_utc ASC").df()
        vix_raw = clean_dataframe(vix_raw, "VIX_RAW")
        vix_raw = calculate_indicators(vix_raw, 'vix_')
        vix_today = vix_raw[vix_raw['dt'].dt.date == market_open_utc.date()].copy()
    except Exception: vix_today = pd.DataFrame()

    con.close()

    # 3. SLICING
    opt_sliced = opt_df[opt_df['dt'] <= cutoff_utc] if not opt_df.empty else pd.DataFrame()
    spx_sliced = spx_df[spx_df['dt'] <= cutoff_utc] if not spx_df.empty else pd.DataFrame()
    vix_sliced = vix_today[vix_today['dt'] <= cutoff_utc] if not vix_today.empty else pd.DataFrame()

    # Helper to get last value or "NaN"
    def get_last(df, col):
        if df.empty or col not in df.columns: return "N/A"
        val = df.iloc[-1][col]
        return f"{val:.3f}" if pd.notnull(val) else "NaN"

    macd_txt = get_last(vix_sliced, 'vix_MACD')
    rsi_txt = get_last(vix_sliced, 'vix_RSI')

    # 4. PLOTTING
    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, 
        row_heights=[0.3, 0.15, 0.15, 0.15, 0.25],
        vertical_spacing=0.03,
        specs=[[{"secondary_y": True}], [{}], [{}], [{}], [{}]],
        subplot_titles=(
            "Option Price", 
            "SPX Context", 
            f"ROW 3: MACD Trend Lines (Val: {macd_txt})", 
            "ROW 4: MACD Histogram (Momentum)", 
            f"ROW 5: VIX RSI (Val: {rsi_txt})"
        )
    )

    # Row 1: Option
    if not opt_sliced.empty:
        # connectgaps=True prevents broken lines
        fig.add_trace(go.Scatter(x=opt_sliced['dt'], y=opt_sliced['close'], mode='lines', name="Option", 
                                 connectgaps=True, line=dict(color='#2962FF', width=2)), row=1, col=1)
        
        if 'SHOW' in reveal_truth:
            entry_slice = opt_df[opt_df['dt'] >= pd.to_datetime(event_timestamp_utc, unit='ms', utc=True)]
            if not entry_slice.empty:
                entry_row = entry_slice.iloc[0]
                if cutoff_utc >= entry_row['dt']:
                    fig.add_trace(go.Scatter(x=[entry_row['dt']], y=[entry_row['close']], mode='markers', 
                                             marker=dict(color='#FFD600', size=14, symbol='triangle-up'), name="Entry"), row=1, col=1)
                    
                    # P&L
                    opt_sliced = opt_sliced.copy()
                    opt_sliced['pct'] = (opt_sliced['close'] - entry_row['close']) / entry_row['close']
                    colors = np.where(opt_sliced['pct'] >= 0, 'rgba(0, 200, 83, 0.3)', 'rgba(198, 40, 40, 0.3)')
                    fig.add_trace(go.Bar(x=opt_sliced['dt'], y=opt_sliced['pct']*100, marker_color=colors, name="P&L"), row=1, col=1, secondary_y=True)

    # Row 2: SPX
    if not spx_sliced.empty:
        fig.add_trace(go.Candlestick(x=spx_sliced['dt'], open=spx_sliced['open'], high=spx_sliced['high'], 
                                     low=spx_sliced['low'], close=spx_sliced['close'], name="SPX"), row=2, col=1)

    # Row 3: VIX MACD LINES (Explicit)
    if not vix_sliced.empty:
        fig.add_trace(go.Scatter(x=vix_sliced['dt'], y=vix_sliced['vix_MACD'], name="MACD Line", 
                                 connectgaps=True, line=dict(color='#FFEA00', width=2)), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_sliced['dt'], y=vix_sliced['vix_Signal'], name="Signal Line", 
                                 connectgaps=True, line=dict(color='#00E5FF', width=2, dash='solid')), row=3, col=1)

    # Row 4: VIX HISTOGRAM
    if not vix_sliced.empty:
        hist_colors = ['#00C853' if v >= 0 else '#D32F2F' for v in vix_sliced['vix_Histogram']]
        fig.add_trace(go.Bar(x=vix_sliced['dt'], y=vix_sliced['vix_Histogram'], marker_color=hist_colors, name="Hist"), row=4, col=1)

    # Row 5: VIX RSI
    if not vix_sliced.empty:
        fig.add_trace(go.Scatter(x=vix_sliced['dt'], y=vix_sliced['vix_RSI'], name="RSI", 
                                 connectgaps=True, line=dict(color='#FF00FF', width=2)), row=5, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=5, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=5, col=1)

    # Final Layout
    fig.update_xaxes(range=[market_open_utc, market_close_utc], row=5, col=1)
    # Force scaling for MACD rows
    for r in [3, 4]: fig.update_yaxes(autorange=True, fixedrange=False, row=r, col=1)
    fig.update_yaxes(range=[0, 100], row=5, col=1)

    for r in [1, 2, 3, 4, 5]:
        fig.add_vline(x=cutoff_utc, line_width=2, line_dash="solid", line_color="#FFD600", opacity=0.7, row=r, col=1)

    fig.update_layout(template="plotly_dark", height=1200, margin=dict(t=40, b=30, l=50, r=50), xaxis_rangeslider_visible=False, showlegend=True)
    
    return fig, f"⏱ Time: {cutoff_utc.astimezone(PST_TZ).strftime('%H:%M PST')}"

if __name__ == '__main__':
    app.run(debug=True, port=8051)