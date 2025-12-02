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
import duckdb
from scipy.stats import norm
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
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
register_page(__name__, path='/', name='Command Center')
logger = get_logger("CommandCenter")

# ==============================================================================
# 3. MATH MODELS
# ==============================================================================
_CACHE = {"live_data": {}, "last_updated": None}

def calculate_technical_indicators(df):
    if df is None or df.empty: return df
    df['ema12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    # RSI
    delta = df['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False, min_periods=14).mean()
    ma_down = down.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

# ==============================================================================
# 4. DATA FETCHING (PROXY MODE)
# ==============================================================================
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

def fetch_data_bundle(force_refresh=False):
    global _CACHE
    now = datetime.now()
    if not force_refresh and _CACHE['last_updated'] and (now - _CACHE['last_updated']).total_seconds() < 60:
        return _CACHE

    try:
        # SWITCHED: Removed 'ES=F', Added 'SPY' for Real-Time Proxy
        tickers = ['^GSPC', '^VIX', 'SPY', '^IRX']
        df_live = yf.download(tickers, period='5d', interval='5m', progress=False, group_by='ticker', session=config.GLOBAL_SESSION)
        
        data_bundle = {}
        
        # 1. SPX (The Truth) - Scaled / 10
        if '^GSPC' in df_live.columns:
            spx = df_live['^GSPC'][['Close', 'Open', 'High', 'Low']].dropna()
            if spx.index.tz is None: spx.index = spx.index.tz_localize(config.TZ_NY)
            else: spx.index = spx.index.tz_convert(config.TZ_NY)
            spx = spx[spx.index >= spx.index[-1].normalize()]
            spx.index = spx.index.tz_convert(config.TZ_LOCAL)
            
            # Scale to XSP ($600 range)
            xsp = spx.copy()
            xsp[['Close', 'Open', 'High', 'Low']] = xsp[['Close', 'Open', 'High', 'Low']] / 10.0
            data_bundle['SPX'] = xsp 
        
        # 2. SPY (The Proxy) - Natural Scale ($600 range)
        if 'SPY' in df_live.columns:
            spy = df_live['SPY'][['Close']].dropna()
            if spy.index.tz is None: spy.index = spy.index.tz_localize(config.TZ_NY)
            else: spy.index = spy.index.tz_convert(config.TZ_NY)
            spy = spy[spy.index >= spy.index[-1].normalize()]
            spy.index = spy.index.tz_convert(config.TZ_LOCAL)
            # No division needed; SPY trades ~1/10 of SPX naturally
            data_bundle['SPY'] = spy

        # 3. VIX (The Engine)
        if '^VIX' in df_live.columns:
            vix = df_live['^VIX'][['Close']].dropna()
            if vix.index.tz is None: vix.index = vix.index.tz_localize(config.TZ_NY)
            else: vix.index = vix.index.tz_convert(config.TZ_NY)
            vix = vix[vix.index >= vix.index[-1].normalize() - timedelta(days=5)].copy()
            vix = calculate_technical_indicators(vix)
            vix_plot = vix[vix.index >= vix.index[-1].normalize()]
            vix_plot.index = vix_plot.index.tz_convert(config.TZ_LOCAL)
            data_bundle['VIX'] = vix_plot
            data_bundle['VIX_LAST'] = float(vix['Close'].iloc[-1])

        # 4. VIX Multi-Timeframe Analysis (MTA)
        vix_bundle = {}
        v1m = yf.download('^VIX', period='1d', interval='1m', progress=False)
        if not v1m.empty: vix_bundle['1m'] = calculate_technical_indicators(v1m)
        v5m = yf.download('^VIX', period='5d', interval='5m', progress=False)
        if not v5m.empty: vix_bundle['5m'] = calculate_technical_indicators(v5m)
        v30m = yf.download('^VIX', period='1mo', interval='30m', progress=False)
        if not v30m.empty: vix_bundle['30m'] = calculate_technical_indicators(v30m)
        v1h = yf.download('^VIX', period='3mo', interval='1h', progress=False)
        if not v1h.empty: vix_bundle['1h'] = calculate_technical_indicators(v1h)
        
        data_bundle['VIX_MTA'] = vix_bundle
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
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 5", className="text-muted mb-0"),
            html.H2("COMMAND CENTER (LIVE SPY PROXY)", className="display-6 fw-bold text-light"),
        ], width=8),
        dbc.Col([html.H4(id='cmd-clock', className="text-end text-info mt-2")], width=4)
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
     Output('cmd-clock', 'children')],
    [Input('cmd-interval', 'n_intervals'),
     Input('cc-refresh-btn', 'n_clicks')]
)
def update_command_center(n, refresh_clicks):
    is_manual = (ctx.triggered_id == 'cc-refresh-btn')
    time_str = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S PST")
    data = fetch_data_bundle(force_refresh=is_manual)
    
    spx = data.get('live_data', {}).get('SPX')
    spy = data.get('live_data', {}).get('SPY') # Now using SPY
    vix_mta = data.get('live_data', {}).get('VIX_MTA', {})
    vix_last = data.get('live_data', {}).get('VIX_LAST', 20.0)

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=False, 
        row_heights=[0.5, 0.3, 0.2],
        vertical_spacing=0.06, 
        specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: XSP (Syn) vs SPY (Proxy)", "VIX Fractal Flow (1H vs 5m)", "VIX RSI")
    )

    # 1. Market Context (XSP vs SPY)
    if spx is not None:
        fig.add_trace(go.Candlestick(
            x=spx.index, open=spx['Open'], high=spx['High'], low=spx['Low'], close=spx['Close'], 
            name="XSP (Syn)"
        ), row=1, col=1)
    
    if spy is not None:
        fig.add_trace(go.Scatter(
            x=spy.index, y=spy['Close'], 
            mode='lines', 
            line=dict(color='#FF9800', width=1.5, dash='solid'), # Orange for SPY
            name="SPY (Real-Time)"
        ), row=1, col=1)

    # 2. VIX Fractal Flow
    if '1h' in vix_mta and '5m' in vix_mta:
        v1h, v5m = vix_mta['1h'], vix_mta['5m']
        colors_1h = ['rgba(102, 187, 106, 0.3)' if v >= 0 else 'rgba(239, 83, 80, 0.3)' for v in v1h['hist']]
        fig.add_trace(go.Bar(x=v1h.index, y=v1h['hist'], marker_color=colors_1h, name="Macro (1h)"), row=2, col=1)
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

    return fig, fig_gauge, news_items, time_str