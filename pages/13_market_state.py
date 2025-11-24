import dash
from dash import dcc, html, Input, Output, register_page, callback
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import dash_bootstrap_components as dbc
from datetime import datetime
import pytz
import logging
import requests
import xml.etree.ElementTree as ET

register_page(__name__, path='/periscope', name='Periscope')

TZ_UTC = pytz.utc
TZ_LOCAL = pytz.timezone('US/Pacific')
logger = logging.getLogger("MarketPeriscope")

# --- DATA FETCHING (Same Logic, Refactored) ---
def fetch_market_snapshot():
    tickers = {'^GSPC': 'S&P 500', '^VIX': 'VIX'}
    data = {}
    try:
        df = yf.download(list(tickers.keys()), period="5d", interval="1d", progress=False)
        # Extract logic simplified for brevity but robust
        for sym, name in tickers.items():
            if isinstance(df.columns, pd.MultiIndex):
                price = df['Close'][sym].iloc[-1]
                prev = df['Close'][sym].iloc[-2]
            else:
                price = df['Close'].iloc[-1]
                prev = df['Close'].iloc[-2]
            
            change = price - prev
            data[sym] = {'name': name, 'price': price, 'change': change, 'pct': (change/prev)*100, 'color': '#00E676' if change >= 0 else '#FF1744'}
    except Exception: return None
    return data

def create_gauge(vix_price):
    val = float(vix_price)
    if val < 15: label, color = "EXTREME GREED", "#00C853"
    elif val < 20: label, color = "NORMAL", "#00E5FF"
    elif val < 30: label, color = "FEAR", "#FF9100"
    else: label, color = "EXTREME FEAR", "#FF1744"
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number", value = val,
        title = {'text': f"{label}", 'font': {'size': 20, 'color': color}},
        gauge = {'axis': {'range': [10, 45]}, 'bar': {'color': color}, 'bgcolor': "white"}
    ))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', font={'color': "white"}, height=250, margin=dict(l=30, r=30, t=30, b=30))
    return fig

def fetch_news():
    news = []
    try:
        r = requests.get("https://finance.yahoo.com/rss/headline?s=SPY", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        root = ET.fromstring(r.content)
        for item in root.findall('.//item')[:4]:
            news.append({'title': item.find('title').text, 'link': item.find('link').text})
    except: pass
    return news

# --- LAYOUT ---
layout = dbc.Container([
    dcc.Interval(id='peri-interval', interval=60*1000, n_intervals=0),
    dbc.Row([dbc.Col(html.H2("🔭 Market Periscope", className="text-center text-light mt-4 mb-4"), width=12)]),
    
    html.Div(id='peri-content')
], fluid=True)

# --- CALLBACK ---
@callback(Output('peri-content', 'children'), Input('peri-interval', 'n_intervals'))
def update_periscope(n):
    data = fetch_market_snapshot()
    news = fetch_news()
    
    if not data: return html.Div("Data Fetch Failed", className="text-danger")

    # Indices
    indices = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([html.H5(d['name']), html.H3(f"{d['price']:.2f}"), html.P(f"{d['pct']:+.2f}%", style={'color': d['color']})]), color="dark", outline=True), width=6)
        for d in data.values()
    ], className="mb-4")

    # Gauge & News
    content = dbc.Row([
        dbc.Col([dcc.Graph(figure=create_gauge(data['^VIX']['price']))], width=12, md=6),
        dbc.Col([
            html.H4("Live Wire (SPY)", className="text-muted mb-3"),
            html.Div([
                html.Div([
                    html.A(item['title'], href=item['link'], target="_blank", className="text-decoration-none text-info fw-bold"),
                    html.Hr(className="my-2")
                ]) for item in news
            ])
        ], width=12, md=6)
    ])
    
    return [indices, content]