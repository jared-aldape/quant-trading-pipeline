import sys
import os
from pathlib import Path
import dash
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc
import webbrowser
from threading import Timer

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION & IMPORTS
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "src" / "tools"))
sys.path.append(str(ROOT_DIR / "src" / "pipeline"))

# ==============================================================================
# 2. APP SETUP (Monolithic Host)
# ==============================================================================
app = Dash(
    __name__, 
    use_pages=True, 
    pages_folder="src/tools", 
    external_stylesheets=[dbc.themes.DARKLY],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
app.title = "QUANT OS v2.2"

# ------------------------------------------------------------------------------
# COMPONENT 1: DESKTOP SIDEBAR (Visible only on Large Screens)
# ------------------------------------------------------------------------------
sidebar = dbc.Nav(
    [
        html.H2("QUANT OS", className="display-6 fw-bold text-success", style={'marginBottom': '20px'}),
        html.Hr(style={'borderColor': '#333'}),
        
        dbc.NavLink([html.Div("1. Backtester (Blue)", className="ms-2")], href="/backtester", active="exact", className="text-info"),
        dbc.NavLink([html.Div("2. Forecaster (Green)", className="ms-2")], href="/forecast", active="exact", className="text-success"),
        dbc.NavLink([html.Div("3. Analysis (Cyan)", className="ms-2")], href="/analysis", active="exact", className="text-info"),
        dbc.NavLink([html.Div("4. Simulator (Orange)", className="ms-2")], href="/simulator", active="exact", className="text-warning"),
        dbc.NavLink([html.Div("5. Live Ops (Red)", className="ms-2")], href="/live", active="exact", className="text-danger"),
        dbc.NavLink([html.Div("6. Periscope (Teal)", className="ms-2")], href="/periscope", active="exact", style={'color': '#20c997'}),
        
        html.Hr(style={'borderColor': '#333', 'marginTop': 'auto'}),
        html.P("Status: DESKTOP", className="text-muted small"),
    ],
    vertical=True,
    pills=True,
    className="bg-dark h-100",
    style={'padding': '20px'}
)

# ------------------------------------------------------------------------------
# COMPONENT 2: MOBILE NAVBAR (Visible only on Phone/Tablet)
# ------------------------------------------------------------------------------
# This component has the built-in "Collapsible" hamburger menu
mobile_navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("1. Backtester", href="/backtester", active="exact")),
        dbc.NavItem(dbc.NavLink("2. Forecaster", href="/forecast", active="exact")),
        dbc.NavItem(dbc.NavLink("3. Analysis", href="/analysis", active="exact")),
        dbc.NavItem(dbc.NavLink("4. Simulator", href="/simulator", active="exact")),
        dbc.NavItem(dbc.NavLink("5. Live Ops", href="/live", active="exact")),
        dbc.NavItem(dbc.NavLink("6. Periscope", href="/periscope", active="exact")),
    ],
    brand="QUANT OS v2.2",
    brand_href="/",
    color="dark",
    dark=True,
    className="d-lg-none mb-3" # CSS Magic: d-lg-none means "Hide on Large screens"
)

# ==============================================================================
# 3. LAYOUT ASSEMBLY (Hybrid)
# ==============================================================================
app.layout = dbc.Container(
    fluid=True,
    style={'backgroundColor': '#111', 'color': '#eee', 'fontFamily': 'monospace', 'minHeight': '100vh'},
    children=[
        dcc.Store(id='global-store'), 

        # 1. MOBILE HEADER (Only shows on phone)
        mobile_navbar,

        dbc.Row([
            # 2. DESKTOP SIDEBAR (Only shows on PC)
            # d-none = Hide always, d-lg-block = Show only on Large screens
            dbc.Col(
                sidebar,
                width=2, 
                className="d-none d-lg-block p-0 border-end border-secondary",
                style={"minHeight": "100vh"}
            ),
            
            # 3. CONTENT AREA
            # On mobile (xs=12), it takes full width. On desktop (lg=10), it sits next to sidebar.
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
    # Browser auto-open disabled to prevent tab spam
    app.run(debug=True, host='0.0.0.0', port=8050)