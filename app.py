import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import pathlib
import sys
import os

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(ROOT_DIR))

from src.utils import config

# IMPORT VIEWS (The Distributed Command System)
from src.interface import (
    view_live,          
    view_scope,         # Live Market (The Monitor)
    view_order_deck,    # Option Simulator (The Executioner)
    view_ledger,        # Ledger Editor (Keep imported for routing fallback)
    view_mobile,        # Mobile Command (Keep imported for routing fallback)
    view_replay,        
    view_backtest,      
    view_chart,         
    view_stats,         
    view_predict,       
    view_growth,        
    view_system_health  
)

def generate_logo_asset():
    """Generates Assets"""
    pass 

generate_logo_asset()

# ==============================================================================
# 2. APP INITIALIZATION
# ==============================================================================
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.CYBORG], 
    suppress_callback_exceptions=True, 
    title="Quant OS v3.3",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ==============================================================================
# 3. LAYOUT (Final Menu Structure)
# ==============================================================================
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    
    dbc.Button(
        "☰", id="open-offcanvas", n_clicks=0, 
        color="primary", className="position-fixed top-0 start-0 m-3", 
        style={"zIndex": "1050"}
    ),

    dbc.Offcanvas(
        html.Div([
            html.Div([
                html.Img(
                    src="/assets/quant_logo.svg", 
                    style={"width": "100%", "maxWidth": "220px", "height": "auto", "display": "block", "margin": "0 auto"}
                )
            ], className="text-center mb-4"),
            
            html.Hr(style={'borderColor': '#333'}),
            
            dbc.Nav([
                html.Small("COMMAND CENTER", className="text-muted mt-2 mb-1 fw-bold"),
                # LIVE / EXECUTION
                dbc.NavLink("Live Market", href="/scope", active="exact"),         
                dbc.NavLink("Option Simulator", href="/simulator", active="exact"),
                
                html.Small("ANALYSIS (PAST)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Data Generator", href="/backtest", active="exact"),
                dbc.NavLink("Chart Analysis", href="/chart", active="exact"),
                dbc.NavLink("Replay Analysis", href="/replay", active="exact"),  # RENAMED
                dbc.NavLink("Statistics Lab", href="/stats", active="exact"),
                
                html.Small("FORECAST (FUTURE)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Capital Growth", href="/growth", active="exact"), # REMOVED PREDICTIVE HUD
                
                html.Hr(className="my-2"),
                dbc.NavLink("System Information", href="/health", active="exact"),
            ], vertical=True, pills=True),
        ]),
        id="offcanvas",
        title="", 
        is_open=False,
        style={"backgroundColor": "#0B0C10", "color": "white", "borderRight": "1px solid #1F2833"}
    ),
    
    html.Div(id='page-content', style={'padding': '20px', 'paddingTop': '80px'}),
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)
])

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@app.callback(
    Output("offcanvas", "is_open"),
    [Input("open-offcanvas", "n_clicks"), Input("url", "pathname")],
    [State("offcanvas", "is_open")],
)
def manage_sidebar(n_clicks, pathname, is_open):
    ctx = dash.callback_context
    if not ctx.triggered: return is_open
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if trigger_id == 'open-offcanvas': return not is_open
    if trigger_id == 'url': return False
    return is_open

@app.callback(Output('page-content', 'children'), [Input('url', 'pathname')])
def display_page(pathname):
    # ROUTING LOGIC (All routes remain active even if links are removed)
    if pathname == '/scope': return view_scope.render()       # Live Market
    elif pathname == '/simulator': return view_order_deck.render() # Execution
    elif pathname == '/ledger': return view_ledger.render()   # Audit (Keep link in case needed)
    elif pathname == '/mobile': return view_mobile.render()   # Phone (Keep link in case needed)
    elif pathname == '/backtest': return view_backtest.render()
    elif pathname == '/chart': return view_chart.render()
    elif pathname == '/replay': return view_replay.render()   # Replay Analysis
    elif pathname == '/stats': return view_stats.render()
    elif pathname == '/predict': return view_predict.render() # Predictive HUD
    elif pathname == '/growth': return view_growth.render()
    elif pathname == '/live': return view_live.render()       
    else: return view_system_health.render()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)