import sys
import os
from pathlib import Path
import dash
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc
import webbrowser
from threading import Timer

# ==============================================================================
# 1. ARCHITECTURE V2.5: PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent

# Register valid python paths for imports
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "src" / "interface")) # New Pages Location
sys.path.append(str(ROOT_DIR / "src" / "core"))      # Engines

# ==============================================================================
# 2. APP SETUP (Monolithic Host)
# ==============================================================================
app = Dash(
    __name__, 
    use_pages=True, 
    pages_folder="src/interface",  # <--- POINTING TO NEW VIEWS
    external_stylesheets=[dbc.themes.DARKLY],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    suppress_callback_exceptions=True
)
app.title = "QUANT OS v2.5"

# ------------------------------------------------------------------------------
# COMPONENT 1: DESKTOP SIDEBAR (Professional Terminal Look)
# ------------------------------------------------------------------------------
sidebar = dbc.Nav(
    [
        html.H2("QUANT OS", className="display-6 fw-bold text-success", style={'marginBottom': '20px'}),
        html.Hr(style={'borderColor': '#333'}),
        
        # CLEAN NAVIGATION (No Numbers, No Colors)
        dbc.NavLink([html.Div("COMMAND CENTER", className="ms-2 fw-bold")], href="/", active="exact", className="text-light mb-2"),
        dbc.NavLink([html.Div("STRATEGY BACKTESTER", className="ms-2")], href="/backtester", active="exact", className="text-muted mb-1"),
        dbc.NavLink([html.Div("FORENSIC ANALYSIS", className="ms-2")], href="/analysis", active="exact", className="text-muted mb-1"),
        dbc.NavLink([html.Div("EXECUTION SIMULATOR", className="ms-2")], href="/simulator", active="exact", className="text-muted mb-1"),
        dbc.NavLink([html.Div("CAPITAL FORECASTER", className="ms-2")], href="/forecast", active="exact", className="text-muted mb-1"),
        
        html.Hr(style={'borderColor': '#333', 'marginTop': 'auto'}),
        html.P("v2.5 | HYBRID ENGINE", className="text-success small opacity-50"),
    ],
    vertical=True,
    pills=True,
    className="bg-black h-100",
    style={'padding': '20px', 'borderRight': '1px solid #333'}
)

# ------------------------------------------------------------------------------
# COMPONENT 2: MOBILE NAVBAR (Phone/Tablet)
# ------------------------------------------------------------------------------
mobile_navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("COMMAND", href="/", active="exact")),
        dbc.NavItem(dbc.NavLink("BACKTEST", href="/backtester", active="exact")),
        dbc.NavItem(dbc.NavLink("ANALYSIS", href="/analysis", active="exact")),
        dbc.NavItem(dbc.NavLink("SIMULATOR", href="/simulator", active="exact")),
        dbc.NavItem(dbc.NavLink("FORECAST", href="/forecast", active="exact")),
    ],
    brand="QUANT OS v2.5",
    brand_href="/",
    color="dark",
    dark=True,
    className="d-lg-none mb-3" 
)

# ==============================================================================
# 3. LAYOUT ASSEMBLY (Hybrid)
# ==============================================================================
app.layout = dbc.Container(
    fluid=True,
    style={'backgroundColor': '#0a0a0a', 'color': '#eee', 'fontFamily': 'monospace', 'minHeight': '100vh'},
    children=[
        dcc.Store(id='global-store'), 

        # 1. MOBILE HEADER (Only shows on phone)
        mobile_navbar,

        dbc.Row([
            # 2. DESKTOP SIDEBAR (Only shows on PC)
            dbc.Col(
                sidebar,
                width=2, 
                className="d-none d-lg-block p-0",
                style={"minHeight": "100vh"}
            ),
            
            # 3. CONTENT AREA
            dbc.Col(
                dash.page_container,
                xs=12, lg=10,
                className="p-4"
            )
        ], className="g-0")
    ]
)

# ==============================================================================
# 4. EXECUTION
# ==============================================================================
if __name__ == '__main__':
    # Auto-open browser for convenience
    Timer(1, lambda: webbrowser.open("http://127.0.0.1:8050/")).start()
    app.run(debug=True, host='0.0.0.0', port=8050)