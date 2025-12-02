import sys
import os
import dash
from dash import dcc, html, Input, Output, State, register_page, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: src/interface/view_command.py
# Root: ../../
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import strat_fractal  # <--- NEW: Centralized Logic

# ==============================================================================
# 2. PAGE REGISTRATION
# ==============================================================================
register_page(__name__, path='/', name='Command Center')
logger = get_logger("CommandView")

# ==============================================================================
# 3. DATA FETCHING (PROXY MODE)
# ==============================================================================
_CACHE = {"live_data": {}, "last_updated": None}

def parse_rss(url):
    items = []
    try:
        resp = config.GLOBAL_SESSION.get(url, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:5]:
                try:
                    title = item.find('title').text
                    link = item.find('link').text
                    dt = pd.to_datetime(item.find('pubDate').text)
                    if dt.tzinfo is None: dt = dt.tz_localize(config.TZ_UTC)
                    time_str = dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
                    items.append({'title': title, 'link': link, 'time': time_str})
                except: continue
    except: pass
    return items

def process_vix_data(df, interval):
    """Standardizes VIX data and applies Strat Fractal indicators."""
    if df is None or df.empty: return df
    
    # 1. Standardize Columns (Lowercase for Strategy Module)
    df.columns = df.columns.str.lower()
    
    # 2. Apply Indicators
    df = strat_fractal.calculate_macd(df)
    df = strat_fractal.calculate_rsi(df)
    
    return df

def fetch_data_bundle(force_refresh=False):
    global _CACHE
    now = datetime.now()
    if not force_refresh and _CACHE['last_updated'] and (now - _CACHE['last_updated']).total_seconds() < 60:
        return _CACHE

    try:
        # Tickers: SPX (Context), VIX (Engine), SPY (Proxy), IRX (Rate)
        tickers = ['^GSPC', '^VIX', 'SPY', '^IRX']
        
        # Download 5m data bundle
        df_live = yf.download(tickers, period='5d', interval='5m', progress=False, group_by='ticker', session=config.GLOBAL_SESSION)
        
        data_bundle = {}
        
        # 1. SPX (The Truth) - Scaled / 10
        if '^GSPC' in df_live.columns:
            spx = df_live['^GSPC'][['Close', 'Open', 'High', 'Low']].dropna()
            spx.columns = spx.columns.str.lower()
            
            # Timezone handling
            if spx.index.tz is None: spx.index = spx.index.tz_localize(config.TZ_NY)
            else: spx.index = spx.index.tz_convert(config.TZ_NY)
            spx = spx[spx.index >= spx.index[-1].normalize()] # Today only
            spx.index = spx.index.tz_convert(config.TZ_LOCAL)
            
            # Scale to XSP ($600 range)
            xsp = spx.copy()
            xsp[['close', 'open', 'high', 'low']] = xsp[['close', 'open', 'high', 'low']] / 10.0
            data_bundle['SPX'] = xsp 
        
        # 2. SPY (The Proxy) - Natural Scale
        if 'SPY' in df_live.columns:
            spy = df_live['SPY'][['Close']].dropna()
            spy.columns = spy.columns.str.lower()
            
            if spy.index.tz is None: spy.index = spy.index.tz_localize(config.TZ_NY)
            else: spy.index = spy.index.tz_convert(config.TZ_NY)
            spy = spy[spy.index >= spy.index[-1].normalize()]
            spy.index = spy.index.tz_convert(config.TZ_LOCAL)
            data_bundle['SPY'] = spy

        # 3. VIX Multi-Timeframe Analysis (MTA)
        # We fetch different intervals individually for the Fractal Logic
        vix_bundle = {}
        
        # 1-Hour (The River) - 3 Months
        v1h = yf.download('^VIX', period='3mo', interval='1h', progress=False)
        if not v1h.empty:
            vix_bundle['1h'] = process_vix_data(v1h, '1h')

        # 5-Minute (The Ripple) - 5 Days
        v5m = yf.download('^VIX', period='5d', interval='5m', progress=False)
        if not v5m.empty:
            vix_bundle['5m'] = process_vix_data(v5m, '5m')

        data_bundle['VIX_MTA'] = vix_bundle
        
        # Get last price for Gauge
        if '5m' in vix_bundle and not vix_bundle['5m'].empty:
             data_bundle['VIX_LAST'] = float(vix_bundle['5m']['close'].iloc[-1])
        else:
             data_bundle['VIX_LAST'] = 0.0

        _CACHE['live_data'] = data_bundle
        _CACHE['news_global'] = parse_rss("https://finance.yahoo.com/rss/topstories")

    except Exception as e:
        logger.error(f"Fetch Fail: {e}")

    _CACHE['last_updated'] = now
    return _CACHE

# ==============================================================================
# 5. LAYOUT
# ==============================================================================
layout = dbc.Container([
    # HEADER ROW
    dbc.Row([
        dbc.Col([
            html.H2("COMMAND CENTER", className="display-6 fw-bold text-white"),
            html.Small("LIVE PROXY FEED (SPY/VIX)", className="text-muted")
        ], width=6),
        dbc.Col([
            html.Div([
                html.Span(id='cmd-status-badge', className="badge bg-secondary me-2", style={'fontSize': '1.2rem'}),
                html.H4(id='cmd-clock', className="text-info d-inline-block m-0")
            ], className="text-end mt-2")
        ], width=6)
    ], className="mb-3"),

    dbc.Row([
        # --- LEFT: CHARTS ---
        dbc.Col([
            dbc.Card([
                dbc.CardBody([dcc.Graph(id='cmd-main-chart', style={'height': '800px'}, config={'displayModeBar': False})], className="p-0")
            ], className="shadow h-100")
        ], width=12, lg=9),

        # --- RIGHT: INFO ---
        dbc.Col([
            # 1. GAUGE
            dbc.Card([
                dbc.CardHeader("Volatility Regime"),
                dbc.CardBody([dcc.Graph(id='cmd-vix-gauge', style={'height': '150px'})], className="p-0")
            ], className="shadow mb-3"),
            
            # 2. NEWS
            dbc.Card([
                dbc.CardHeader("Global Wire"),
                dbc.CardBody(id='cmd-news-global', style={'maxHeight': '400px', 'overflowY': 'auto'})
            ], className="shadow mb-3"),

            dbc.Button("🔄 Force Sync", id='cc-refresh-btn', color="secondary", outline=True, className="w-100")

        ], width=12, lg=3)
    ], className="mb-4"),

    dcc.Interval(id='cmd-interval', interval=60*1000, n_intervals=0)
], fluid=True)

# ==============================================================================
# 6. CALLBACKS
# ==============================================================================
@callback(
    [Output('cmd-main-chart', 'figure'),
     Output('cmd-vix-gauge', 'figure'),
     Output('cmd-news-global', 'children'),
     Output('cmd-clock', 'children'),
     Output('cmd-status-badge', 'children'),
     Output('cmd-status-badge', 'className')],
    [Input('cmd-interval', 'n_intervals'),
     Input('cc-refresh-btn', 'n_clicks')]
)
def update_command_center(n, refresh_clicks):
    is_manual = (ctx.triggered_id == 'cc-refresh-btn')
    time_str = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S PST")
    
    data = fetch_data_bundle(force_refresh=is_manual)
    
    spx = data.get('live_data', {}).get('SPX')
    spy = data.get('live_data', {}).get('SPY') 
    vix_mta = data.get('live_data', {}).get('VIX_MTA', {})
    vix_last = data.get('live_data', {}).get('VIX_LAST', 20.0)

    # --- SIGNAL CHECK (The Brain) ---
    signal_status = "WAIT"
    signal_class = "badge bg-secondary me-2"
    
    if '1h' in vix_mta and '5m' in vix_mta:
        # Check Strategy
        decision = strat_fractal.check_fractal_setup(vix_mta['1h'], vix_mta['5m'])
        
        if decision['signal']:
            signal_status = "ARMED"
            signal_class = "badge bg-success me-2 blink-me" # CSS animation suggested for blink
        elif decision['macro_trend'] == "BEARISH_VOL (SAFE)":
            signal_status = "MACRO READY"
            signal_class = "badge bg-info me-2"
        else:
            signal_status = "NO SIGNAL"
            signal_class = "badge bg-dark me-2"

    # --- PLOTTING ---
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=False, 
        row_heights=[0.5, 0.3, 0.2],
        vertical_spacing=0.06, 
        specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: XSP (Syn) vs SPY (Proxy)", "VIX Fractal Flow (1H vs 5m)", "VIX RSI")
    )

    # 1. Market Context
    if spx is not None:
        fig.add_trace(go.Candlestick(
            x=spx.index, open=spx['open'], high=spx['high'], low=spx['low'], close=spx['close'], 
            name="XSP (Syn)"
        ), row=1, col=1)
    
    if spy is not None:
        fig.add_trace(go.Scatter(
            x=spy.index, y=spy['close'], 
            mode='lines', 
            line=dict(color='#FF9800', width=1.5, dash='solid'), # Orange for SPY
            name="SPY (Real-Time)"
        ), row=1, col=1)

    # 2. VIX Fractal Flow
    if '1h' in vix_mta and '5m' in vix_mta:
        v1h, v5m = vix_mta['1h'], vix_mta['5m']
        
        # We slice 1H to show recent context (last 5 days aligned with 5m)
        v1h_plot = v1h[v1h.index >= v5m.index[0]] if not v5m.empty else v1h.tail(50)
        
        colors_1h = ['rgba(102, 187, 106, 0.3)' if v < 0 else 'rgba(239, 83, 80, 0.3)' for v in v1h_plot['hist']]
        # NOTE: Logic Inversion -> Negative Hist is Bullish for Stocks (Green), Positive is Bearish (Red)
        # But for VIX itself: Negative Hist = Falling Vol = Green Overlay
        
        fig.add_trace(go.Bar(x=v1h_plot.index, y=v1h_plot['hist'], marker_color=colors_1h, name="Macro (1h)"), row=2, col=1)
        fig.add_trace(go.Scatter(x=v5m.index, y=v5m['macd'], line=dict(color='#FFEB3B', width=1.5), name="Micro (5m)"), row=2, col=1)
        fig.add_trace(go.Scatter(x=v5m.index, y=v5m['signal'], line=dict(color='#00E5FF', width=1, dash='dot'), name="Signal"), row=2, col=1)

    # 3. VIX RSI
    if '5m' in vix_mta:
        v5m = vix_mta['5m']
        fig.add_trace(go.Scatter(x=v5m.index, y=v5m['rsi'], line=dict(color='#7E57C2', width=2), name="RSI"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    fig.update_layout(template="plotly_dark", height=800, margin=dict(l=40, r=40, t=30, b=30), showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    news_items = [html.Div([html.Small(i['time'], className="text-info me-2"), html.A(i['title'], href=i['link'], target="_blank", className="text-white text-decoration-none"), html.Hr(className="my-1 border-secondary")]) for i in data.get('news_global', [])] or [html.Div("No wires.", className="text-muted small")]
    
    fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=vix_last, title={'text': "VIX", 'font': {'size': 16, 'color': 'white'}}, gauge={'axis': {'range': [10, 40]}, 'bar': {'color': "#FF1744" if vix_last > 20 else "#00E676"}, 'bgcolor': "black"}))
    fig_gauge.update_layout(paper_bgcolor='rgba(0,0,0,0)', font={'color': "white"}, height=150, margin=dict(l=20, r=20, t=20, b=20))

    return fig, fig_gauge, news_items, time_str, signal_status, signal_class