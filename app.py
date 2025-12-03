import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import yfinance as yf
import pandas as pd
import duckdb
import pathlib
import sys
from datetime import datetime

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.interface import (
    view_backtester, 
    view_simulator, 
    view_forensics, 
    view_forecast,
    view_capital,
    view_signal_replay,
    view_training_gym
)

# Initialize App with Cyborg Theme (High Contrast Dark Mode)
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG], suppress_callback_exceptions=True)
server = app.server

# ==============================================================================
# 2. LAYOUT: HAMBURGER MENU & CONTENT
# ==============================================================================
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    
    # HAMBURGER BUTTON
    dbc.Button(
        "☰", id="open-offcanvas", n_clicks=0, 
        color="primary", className="position-fixed top-0 start-0 m-3", 
        style={"zIndex": "1050"}
    ),

    # SIDEBAR MENU (Renamed for Simplicity)
    dbc.Offcanvas(
        html.Div([
            html.H4("QUANT OS v3.0", className="text-white mb-4"),
            html.Hr(),
            dbc.Nav([
                # Live Operations
                dbc.NavLink("Live Trading", href="/", active="exact"),           # Was: Live Options Simulator
                dbc.NavLink("Practice Mode", href="/gym", active="exact"),       # Was: Training Gym
                
                # Analysis Suite
                dbc.NavLink("Historical Test", href="/backtester", active="exact"), # Was: Backtester
                dbc.NavLink("Trade Auditor", href="/replay", active="exact"),       # Was: Signal Replay
                dbc.NavLink("Performance Stats", href="/forensics", active="exact"),# Was: Forensics Lab
                
                # Projections
                dbc.NavLink("Intraday Targets", href="/forecast", active="exact"),  # Was: Prophet
                dbc.NavLink("Growth Projection", href="/capital", active="exact"),  # Was: Capital Lab
            ], vertical=True, pills=True),
        ]),
        id="offcanvas",
        title="Menu",
        is_open=False,
        style={"backgroundColor": "#111", "color": "white"}
    ),
    
    # MAIN CONTENT AREA
    html.Div(id='page-content', style={'padding': '20px', 'paddingTop': '80px'}),
    
    # DATA HEARTBEAT (60s)
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)
])

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================

@app.callback(
    Output("offcanvas", "is_open"),
    Input("open-offcanvas", "n_clicks"),
    [State("offcanvas", "is_open")],
)
def toggle_offcanvas(n1, is_open):
    if n1: return not is_open
    return is_open

@app.callback(Output('page-content', 'children'), [Input('url', 'pathname')])
def display_page(pathname):
    # Routing logic remains consistent with file names to ensure stability
    if pathname == '/backtester': return view_backtester.render()
    elif pathname == '/replay': return view_signal_replay.render()
    elif pathname == '/gym': return view_training_gym.render()
    elif pathname == '/forensics': return view_forensics.render()
    elif pathname == '/forecast': return view_forecast.render()
    elif pathname == '/capital': return view_capital.render()
    # Default Route -> Live Trading (Simulator)
    else: return view_simulator.render()

if __name__ == '__main__':
    app.run(debug=True, port=8050)