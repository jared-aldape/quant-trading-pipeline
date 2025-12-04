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

# IMPORT VIEWS
from src.interface import (
    view_live,      
    view_practice,  
    view_backtest,  
    view_audit,     
    view_stats,     
    view_predict,   
    view_growth,    
    view_system_health 
)

# Initialize App with Cyborg Theme AND Proper Browser Title
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.CYBORG], 
    suppress_callback_exceptions=True,
    title="Quant OS v3.1" # <--- FIXED: Browser Tab Title
)
server = app.server

# ==============================================================================
# 2. LAYOUT: CHRONOLOGICAL MENU
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
                # 0. SYSTEM
                html.Small("SYSTEM STATUS", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Health Monitor", href="/health", active="exact"),
                
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                # 1. PRESENT
                html.Small("PRESENT (EXECUTION)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Live Trading", href="/live", active="exact"),
                
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                # 2. PAST
                html.Small("PAST (ANALYSIS)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Backtest Engine", href="/backtest", active="exact"),
                dbc.NavLink("Practice Mode", href="/practice", active="exact"),
                dbc.NavLink("Trade Auditor", href="/audit", active="exact"),
                dbc.NavLink("Performance Stats", href="/stats", active="exact"),

                html.Hr(className="my-2", style={'opacity': '0.3'}),

                # 3. FUTURE
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
# 3. ROUTING & INTERACTION LOGIC
# ==============================================================================

# COMBINED CALLBACK: Handles Menu Toggle AND Auto-Close on Navigation
@app.callback(
    Output("offcanvas", "is_open"),
    [Input("open-offcanvas", "n_clicks"), Input("url", "pathname")],
    [State("offcanvas", "is_open")],
)
def manage_sidebar(n_clicks, pathname, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # If Button Clicked -> Toggle Menu
    if trigger_id == 'open-offcanvas':
        return not is_open
    
    # If URL Changed (Navigation) -> Close Menu
    if trigger_id == 'url':
        return False
        
    return is_open

@app.callback(Output('page-content', 'children'), [Input('url', 'pathname')])
def display_page(pathname):
    if pathname == '/health' or pathname == '/': return view_system_health.render()
    elif pathname == '/live': return view_live.render()
    elif pathname == '/backtest': return view_backtest.render()
    elif pathname == '/practice': return view_practice.render()
    elif pathname == '/audit': return view_audit.render()
    elif pathname == '/stats': return view_stats.render()
    elif pathname == '/predict': return view_predict.render()
    elif pathname == '/growth': return view_growth.render()
    else: return view_system_health.render()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)