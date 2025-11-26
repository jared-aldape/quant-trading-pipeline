import sys
import os
import dash
from dash import dcc, html, Input, Output, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
import logging
from datetime import datetime
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
register_page(__name__, path='/periscope', name='Periscope')

logger = get_logger("MarketPeriscope")

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def fetch_market_snapshot():
    tickers = {'^GSPC': 'S&P 500', '^DJI': 'Dow Jones', '^IXIC': 'Nasdaq', '^VIX': 'VIX'}
    data = {}
    try:
        # Fetch 5 days to ensure we get change calculation even after weekend
        df = yf.download(list(tickers.keys()), period="5d", interval="1d", progress=False)
        is_multi = isinstance(df.columns, pd.MultiIndex)
        
        for sym, name in tickers.items():
            closes = df['Close'][sym].dropna() if is_multi else df['Close'].dropna()
            
            if len(closes) < 2: 
                continue
                
            price, prev = closes.iloc[-1], closes.iloc[-2]
            change = price - prev
            pct_change = (change / prev) * 100
            
            # High Contrast Color Logic
            color = '#00E676' if change >= 0 else '#FF1744'
            
            data[sym] = {
                'name': name, 
                'price': price, 
                'change': change, 
                'pct': pct_change, 
                'color': color
            }
    except Exception as e:
        logger.error(f"Snapshot Error: {e}")
        return None
    return data

def fetch_news():
    """
    Fetches Yahoo Finance TOP STORIES (Broad Market News).
    ENFORCES TIMEZONE LAW: Converts PubDate -> Local Time (PST).
    """
    news_items = []
    rss_url = "https://finance.yahoo.com/rss/topstories" 
    
    try:
        response = requests.get(rss_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            
            for item in root.findall('.//item')[:6]:
                pub_date = item.find('pubDate')
                time_str = "Recent"
                
                if pub_date is not None:
                    try:
                        # 1. Parse & Localize to UTC (if naive)
                        dt = pd.to_datetime(pub_date.text)
                        if dt.tzinfo is None: 
                            dt = dt.tz_localize(config.TZ_UTC)
                        
                        # 2. Convert to Local (Glass)
                        dt_local = dt.astimezone(config.TZ_LOCAL)
                        time_str = dt_local.strftime('%H:%M PST')
                    except: 
                        pass
                
                news_items.append({
                    'title': item.find('title').text, 
                    'link': item.find('link').text, 
                    'time': time_str
                })
    except Exception as e:
        logger.warning(f"News Fetch Error: {e}")
        pass
        
    return news_items

def create_gauge(vix_price):
    val = float(vix_price)
    
    # Regime Logic (VIX Buckets)
    if val < 15: 
        label, color = "EXTREME GREED", "#00C853"
    elif val < 20: 
        label, color = "NORMAL", "#00E5FF"
    elif val < 30: 
        label, color = "FEAR", "#FF9100"
    else: 
        label, color = "EXTREME FEAR", "#FF1744"
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number", 
        value = val,
        title = {'text': label, 'font': {'size': 20, 'color': color}},
        gauge = {
            'axis': {'range': [10, 45]}, 
            'bar': {'color': color}, 
            'bgcolor': "white"
        }
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', 
        font={'color': "white"}, 
        height=300, 
        margin=dict(l=30, r=30, t=30, b=30)
    )
    return fig

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
layout = dbc.Container([
    # HEADER: Standardized Teal Theme
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 6", className="text-muted mb-0"),
            html.H2("MARKET PERISCOPE", className="display-6 fw-bold", style={'color': '#20c997'}),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    # ROW 1: INDICES
    html.Div(id='peri-indices-row'),

    # ROW 2: GAUGE + NEWS
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-speedometer2 me-2"), "Volatility Regime"]),
                dbc.CardBody([dcc.Graph(id='peri-gauge')], className="p-0")
            ], className="shadow mb-4")
        ], width=12, lg=6),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-newspaper me-2"), "Global Top Stories"]),
                dbc.CardBody(id='peri-news-feed', style={'maxHeight': '350px', 'overflowY': 'auto'})
            ], className="shadow mb-4")
        ], width=12, lg=6)
    ]),

    dcc.Interval(id='peri-interval', interval=60*1000, n_intervals=0)
], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    [Output('peri-indices-row', 'children'), Output('peri-gauge', 'figure'), Output('peri-news-feed', 'children')],
    [Input('peri-interval', 'n_intervals')]
)
def update_periscope(n):
    market_data = fetch_market_snapshot()
    news_items = fetch_news()
    
    # 1. INDICES CARDS
    if market_data:
        cards = []
        for sym in ['^GSPC', '^DJI', '^IXIC', '^VIX']:
            if sym in market_data:
                d = market_data[sym]
                cards.append(dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6(d['name'], className="text-muted text-uppercase small mb-1"),
                            html.H3(f"{d['price']:,.2f}", className="metric-value text-white"),
                            html.P(f"{d['change']:+.2f} ({d['pct']:+.2f}%)", style={'color': d['color'], 'fontWeight': 'bold', 'marginBottom': 0})
                        ])
                    ], className="mb-3 border-secondary")
                ], width=12, sm=6, lg=3))
        indices_layout = dbc.Row(cards)
        gauge_fig = create_gauge(market_data['^VIX']['price'])
    else:
        indices_layout = html.Div("Data Link Offline", className="text-danger text-center")
        gauge_fig = go.Figure()

    # 2. NEWS FEED
    news_layout = []
    if news_items:
        for item in news_items:
            news_layout.append(html.Div([
                html.A(item['title'], href=item['link'], target="_blank", className="text-decoration-none fw-bold text-white d-block mb-1", style={'fontSize': '0.95rem'}),
                html.Small(item['time'], className="text-muted"),
                html.Hr(className="border-secondary my-2")
            ]))
    else:
        news_layout = html.Div("Connecting to Wire...", className="text-muted small")

    return indices_layout, gauge_fig, news_layout