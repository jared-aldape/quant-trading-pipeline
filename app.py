import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import pathlib
import sys

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(ROOT_DIR))

from src.utils import config

# IMPORT NEW "FUNCTIONAL" MODULE NAMES
from src.interface import (
    view_live,      # Was view_simulator
    view_practice,  # Was view_training_gym
    view_backtest,  # Was view_backtester
    view_audit,     # Was view_signal_replay
    view_stats,     # Was view_forensics
    view_predict,   # Was view_forecast
    view_growth,    # Was view_capital
    view_system_health # <--- NEW IMPORT
)

# Initialize App with Cyborg Theme
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG], suppress_callback_exceptions=True)
server = app.server

# ==============================================================================
# 2. LAYOUT: CHRONOLOGICAL MENU (System -> Past -> Present -> Future)
# ==============================================================================
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    
    # HAMBURGER BUTTON
    dbc.Button(
        "☰", id="open-offcanvas", n_clicks=0, 
        color="primary", className="position-fixed top-0 start-0 m-3", 
        style={"zIndex": "1050"}
    ),

    # SIDEBAR MENU
    dbc.Offcanvas(
        html.Div([
            html.H4("QUANT OS v3.1", className="text-white mb-4", style={'letterSpacing': '2px'}),
            html.Hr(),
            
            dbc.Nav([
                # 0. SYSTEM (The Pulse)
                html.Small("SYSTEM STATUS", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Health Monitor", href="/health", active="exact"), # Default Home
                
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                # 1. PRESENT (The Now)
                html.Small("PRESENT (EXECUTION)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Live Trading", href="/live", active="exact"),
                
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                # 2. PAST (The Analysis)
                html.Small("PAST (ANALYSIS)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Backtest Engine", href="/backtest", active="exact"),
                dbc.NavLink("Practice Mode", href="/practice", active="exact"),
                dbc.NavLink("Trade Auditor", href="/audit", active="exact"),
                dbc.NavLink("Performance Stats", href="/stats", active="exact"),

                html.Hr(className="my-2", style={'opacity': '0.3'}),

                # 3. FUTURE (The Projection)
                html.Small("FUTURE (FORECAST)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Predictive Analysis", href="/predict", active="exact"),
                dbc.NavLink("Growth Calculator", href="/growth", active="exact"),
                
            ], vertical=True, pills=True),
        ]),
        id="offcanvas",
        title="Tactical Command",
        is_open=False,
        style={"backgroundColor": "#0a0a0a", "color": "white", "borderRight": "1px solid #333"}
    ),
    
    # MAIN CONTENT AREA
    html.Div(id='page-content', style={'padding': '20px', 'paddingTop': '80px'}),
    
    # DATA HEARTBEAT (60s)
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)
])

# ==============================================================================
# 3. ROUTING LOGIC
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
    # SYSTEM (Default Landing)
    if pathname == '/health' or pathname == '/': return view_system_health.render()
    
    # PRESENT
    elif pathname == '/live': return view_live.render()
    
    # PAST
    elif pathname == '/backtest': return view_backtest.render()
    elif pathname == '/practice': return view_practice.render()
    elif pathname == '/audit': return view_audit.render()
    elif pathname == '/stats': return view_stats.render()
    
    # FUTURE
    elif pathname == '/predict': return view_predict.render()
    elif pathname == '/growth': return view_growth.render()
    
    # Fallback to Health Monitor
    else: return view_system_health.render()

if __name__ == '__main__':
    # ---------------------------------------------------------
    # DOCKER NETWORKING FIX
    # ---------------------------------------------------------
    # host='0.0.0.0' exposes the server to the outside world (Host PC).
    # Without this, Docker keeps the port locked to internal localhost only.
    app.run(debug=True, host='0.0.0.0', port=8050)