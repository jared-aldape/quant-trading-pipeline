import sys
import dash
from dash import dcc, html, Input, Output, callback, State, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import duckdb
import pandas as pd
import numpy as np
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
from src.core import strat_fractal

log = get_logger("TrainingGym")
STRIKE_RANGE = 2

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def clean_dataframe(df, target_timezone=config.TZ_LOCAL):
    """Standardizes DataFrames for UI Display (UTC -> Local)."""
    if df is None or df.empty: return pd.DataFrame(columns=['dt', 'close'])
    
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'date': 'dt', 'timestamp': 'dt', 'close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    
    if 'dt' not in df.columns: return pd.DataFrame(columns=['dt', 'close'])
    
    if not pd.api.types.is_datetime64_any_dtype(df['dt']):
        df['dt'] = pd.to_datetime(df['dt'], errors='coerce')
    
    df = df.dropna(subset=['dt'])
    
    if df['dt'].dt.tz is None:
        df['dt'] = df['dt'].dt.tz_localize(config.TZ_UTC)
    else:
        df['dt'] = df['dt'].dt.tz_convert(config.TZ_UTC)
    
    df['dt'] = df['dt'].dt.tz_convert(target_timezone)
    return df.sort_values('dt')

def get_signal_events():
    """Fetches valid signals from the Manifest."""
    if not config.DB_FILE.exists(): return []
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        # Check table
        tables = con.execute("SHOW TABLES").fetchall()
        if (config.TBL_MANIFEST,) not in tables:
            con.close()
            return []
            
        df = con.execute(f"SELECT date, entry_timestamp_utc, xsp_price, trade_type FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC").df()
        con.close()
        
        options = []
        for _, row in df.iterrows():
            ts_utc = pd.to_datetime(row['entry_timestamp_utc'], unit='ms', utc=True)
            ts_local = ts_utc.tz_convert(config.TZ_LOCAL)
            trade_type = row.get('trade_type', 'CALL').upper()
            label = f"{ts_local.strftime('%Y-%m-%d %H:%M')} | {trade_type} | Est. ATM: ${row['xsp_price']:.2f}"
            options.append({'label': label, 'value': row['entry_timestamp_utc']})
        return options
    except: return []

def get_tickers_for_event(event_ts):
    if not event_ts: return [], None
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        row = con.execute(f"SELECT date, xsp_price, trade_type FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_ts}").df().iloc[0]
        trade_date = pd.to_datetime(row['date'])
        atm = round(row['xsp_price'])
        
        t_type = row.get('trade_type', 'call')
        if pd.isna(t_type): t_type = 'call'
        type_letter = 'P' if t_type.lower() == 'put' else 'C'
        
        tickers = []
        best = None
        date_str = trade_date.strftime("%y%m%d")
        
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
            strike = atm + offset
            ticker = f"O:XSP{date_str}{type_letter}{int(strike*1000):08d}"
            lbl = f"{ticker} ({'ATM' if offset==0 else 'OTM' if offset>0 else 'ITM'} ${strike})"
            tickers.append({'label': lbl, 'value': ticker})
            if offset == 0: best = ticker
            
        con.close()
        return tickers, best
    except: return [], None

# ==============================================================================
# 3. RENDER LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("TRAINING GYM (Fog of War)", className="display-6 fw-bold text-white"),
                html.Small("Historical Replay Simulation - Test Your Execution Skills", className="text-muted"),
                html.Hr(className="my-2")
            ], width=12)
        ], className="mb-4"),

        # CONTROLS
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("🎮 SIMULATION CONTROL", className="fw-bold text-success", style={'backgroundColor': '#1a1a1a', 'borderBottom': '1px solid #333'}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("1. Select Session (Signal)", className="text-white small"),
                                dcc.Dropdown(
                                    id='gym-event-selector', 
                                    options=get_signal_events(), 
                                    clearable=False, 
                                    className="mb-2", 
                                    style={'color': '#000'}
                                )
                            ], width=12, md=6),
                            dbc.Col([
                                html.Label("2. Select Contract", className="text-white small"),
                                dcc.Dropdown(
                                    id='gym-strike-selector', 
                                    options=[], 
                                    disabled=True, 
                                    clearable=False, 
                                    style={'color': '#000'}
                                )
                            ], width=12, md=6)
                        ], className="mb-3"),

                        # PLAYBACK
                        dbc.Row([
                            dbc.Col([
                                dbc.ButtonGroup([
                                    dbc.Button("▶ Play", id='gym-play-btn', color="success", outline=False),
                                    dbc.Button("⏸ Pause", id='gym-pause-btn', color="warning", outline=False),
                                ], className="me-2")
                            ], width="auto"),
                            
                            dbc.Col([
                                dcc.Slider(
                                    id='gym-time-slider',
                                    min=0, max=390, step=1, value=0,
                                    marks={0: 'Open', 60: '10:30', 195: 'Mid', 330: '15:00', 390: 'Close'},
                                )
                            ], width=True, className="align-self-center")
                        ], className="mb-2"),
                        
                        dbc.Row([
                             dbc.Col([
                                dbc.Checklist(
                                    options=[{"label": " Reveal Algo Entry (Cheat)", "value": "SHOW"}],
                                    value=[], id="gym-reveal-truth", switch=True, className="text-danger fw-bold"
                                )
                             ], width=6),
                             dbc.Col([
                                 html.H4(id='gym-clock-display', children="--:-- PST", className="text-end text-info font-monospace")
                             ], width=6)
                        ])
                    ], style={'backgroundColor': '#0a0a0a'})
                ], className="mb-3 shadow", style={'border': '1px solid #333'})
            ], width=12)
        ]),

        # CHART
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("LIVE REPLAY", className="fw-bold text-white", style={'backgroundColor': '#1a1a1a', 'borderBottom': '1px solid #333'}),
                    dbc.CardBody([
                        dcc.Graph(id='gym-chart', style={'height': '800px'})
                    ], className="p-1", style={'backgroundColor': '#000'})
                ], className="shadow mb-5", style={'border': '1px solid #333'})
            ], width=12)
        ]),

        dcc.Interval(id='gym-auto-stepper', interval=1000, n_intervals=0, disabled=True),
        dcc.Store(id='gym-state', data={'playing': False})

    ], fluid=True, style={'backgroundColor': '#000', 'minHeight': '100vh'})

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    [Output('gym-strike-selector', 'options'), Output('gym-strike-selector', 'value'), Output('gym-strike-selector', 'disabled')],
    [Input('gym-event-selector', 'value')]
)
def update_sim_dropdown(ts):
    if not ts: return [], None, True
    opts, best = get_tickers_for_event(ts)
    return opts, best, False

@callback(
    [Output('gym-auto-stepper', 'disabled'), Output('gym-state', 'data')],
    [Input('gym-play-btn', 'n_clicks'), Input('gym-pause-btn', 'n_clicks')],
    [State('gym-state', 'data')]
)
def toggle_simulation(play, pause, state):
    trigger = ctx.triggered_id
    if trigger == 'gym-play-btn': return False, {'playing': True}
    return True, {'playing': False}

@callback(
    Output('gym-time-slider', 'value'),
    [Input('gym-auto-stepper', 'n_intervals')],
    [State('gym-time-slider', 'value'), State('gym-time-slider', 'max')]
)
def auto_advance(n, val, max_val):
    return val + 5 if val < max_val else val

@callback(
    [Output('gym-chart', 'figure'), Output('gym-clock-display', 'children')],
    [Input('gym-event-selector', 'value'), Input('gym-strike-selector', 'value'),
     Input('gym-time-slider', 'value'), Input('gym-reveal-truth', 'value')]
)
def render_simulation(ts, ticker, mins, reveal):
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if not ts or not ticker: return empty_fig, "--:--"

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    try:
        # 1. ESTABLISH TIMELINE (The Anchor)
        trade_row = con.execute(f"SELECT date FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {ts}").df().iloc[0]
        trade_date_str = str(pd.to_datetime(trade_row['date']).date())
        
        # A. Market Open in NY (For Slider Logic)
        ny_tz = pytz.timezone("America/New_York")
        market_open_ny = ny_tz.localize(pd.Timestamp(f"{trade_date_str} 09:30:00"))
        
        # B. Cutoff in UTC (The Fog of War Barrier)
        cutoff_utc = (market_open_ny + timedelta(minutes=mins)).astimezone(pytz.utc)
        
        # C. Day Clipper (Midnight Local -> UTC)
        local_start_of_day = pd.Timestamp(f"{trade_date_str} 00:00:00").tz_localize(config.TZ_LOCAL)
        clip_start_utc = local_start_of_day.astimezone(config.TZ_UTC)

        # 2. DATA LOADING (UTC)
        # OPTION DATA = UTC (Polygon)
        opt_df = clean_dataframe(
            con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' ORDER BY datetime_utc ASC").df(),
            target_timezone=config.TZ_LOCAL
        )
        
        # SPX/VIX DATA = UTC (YFinance via New Pipeline)
        spx_df = clean_dataframe(
            con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='SPX' AND CAST(datetime_utc AS DATE)='{trade_date_str}' ORDER BY datetime_utc ASC").df(),
            target_timezone=config.TZ_LOCAL
        )
        
        # Fetch VIX up to today for calculations
        start_date = str(pd.to_datetime(trade_date_str) - timedelta(days=60))
        vix_raw = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND CAST(datetime_utc AS DATE) BETWEEN '{start_date}' AND '{trade_date_str}' ORDER BY datetime_utc ASC").df()
        
        # Standardize for Calcs (Keep UTC for internal math)
        if not vix_raw.empty:
            vix_raw.rename(columns={'datetime_utc': 'dt'}, inplace=True)
            if vix_raw['dt'].dt.tz is None: vix_raw['dt'] = vix_raw['dt'].dt.tz_localize(config.TZ_UTC)
            else: vix_raw['dt'] = vix_raw['dt'].dt.tz_convert(config.TZ_UTC)
            
            # USE STRATEGY MODULE
            vix_raw = strat_fractal.calculate_macd(vix_raw)
            vix_raw = strat_fractal.calculate_rsi(vix_raw)
            
            # Convert to Local for Plotting
            vix_raw['dt'] = vix_raw['dt'].dt.tz_convert(config.TZ_LOCAL)
            
            # Clip to RTH
            rth_open_local = market_open_ny.astimezone(config.TZ_LOCAL)
            vix_today = vix_raw[vix_raw['dt'] >= rth_open_local]
        else:
            vix_today = pd.DataFrame()

        # APPLY FOG OF WAR (Filter by Cutoff time)
        cutoff_local = cutoff_utc.astimezone(config.TZ_LOCAL)
        
        opt_slice = opt_df[opt_df['dt'] <= cutoff_local].copy() if not opt_df.empty else pd.DataFrame()
        spx_slice = spx_df[spx_df['dt'] <= cutoff_local].copy() if not spx_df.empty else pd.DataFrame()
        vix_slice = vix_today[vix_today['dt'] <= cutoff_local].copy() if not vix_today.empty else pd.DataFrame()

    except Exception as e:
        log.error(f"Gym Render Error: {e}")
        con.close()
        return empty_fig, "Data Error"
    
    con.close()

    display_clock = cutoff_local.strftime("%H:%M PST")

    # 5. PLOT
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        row_heights=[0.4, 0.3, 0.15, 0.15],
        vertical_spacing=0.02,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: SPX (Price Action)", "Option Price (Execution)", "VIX MACD (Momentum)", "VIX RSI (Trend)")
    )

    if not spx_slice.empty:
        fig.add_trace(go.Candlestick(
            x=spx_slice['dt'], open=spx_slice['open'], high=spx_slice['high'], low=spx_slice['low'], close=spx_slice['close'], 
            name="SPX", increasing_line_color='#00bc8c', decreasing_line_color='#ef5350'
        ), row=1, col=1)

    if not opt_slice.empty:
        fig.add_trace(go.Scatter(
            x=opt_slice['dt'], y=opt_slice['close'], 
            mode='lines', line=dict(color='#FFFFFF', width=2), name="Option Price"
        ), row=2, col=1, secondary_y=False)
        
        # ENTRY SIGNAL FIX
        if reveal and 'SHOW' in reveal:
             entry_dt_utc = pd.to_datetime(ts, unit='ms', utc=True)
             entry_dt_local = entry_dt_utc.tz_convert(config.TZ_LOCAL)
             
             if cutoff_local >= entry_dt_local:
                 fig.add_vline(x=entry_dt_local, line_dash="dash", line_color="#ffff00", row=2, col=1)
                 try:
                     price_at_entry = opt_df[opt_df['dt'] >= entry_dt_local].iloc[0]['close']
                     fig.add_trace(go.Scatter(
                         x=[entry_dt_local], y=[price_at_entry], 
                         mode='markers', marker=dict(color='#ffff00', size=15, symbol='triangle-up'), name="Algo Entry"
                     ), row=2, col=1)
                 except: pass

    if not vix_slice.empty:
        # Note: strat_fractal produces 'hist', 'macd', 'signal'
        # Negative Hist = Bullish (Green)
        colors = ['#00bc8c' if v < 0 else '#ef5350' for v in vix_slice['hist']]
        fig.add_trace(go.Bar(x=vix_slice['dt'], y=vix_slice['hist'], marker_color=colors, name="Hist"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_slice['dt'], y=vix_slice['macd'], line=dict(color='#f39c12', width=1.5), name="MACD"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_slice['dt'], y=vix_slice['signal'], line=dict(color='#00d2ff', width=1.5), name="Signal"), row=3, col=1)

    if not vix_slice.empty:
        fig.add_trace(go.Scatter(x=vix_slice['dt'], y=vix_slice['rsi'], line=dict(color='#9b59b6', width=2), name="RSI"), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ef5350", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    fig.update_layout(
        template="plotly_dark", 
        height=1000, 
        showlegend=False, 
        margin=dict(t=30, b=30, l=60, r=60),
        xaxis_rangeslider_visible=False,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color="white"),
        yaxis=dict(gridcolor='#333'), xaxis=dict(gridcolor='#333')
    )
    
    return fig, display_clock