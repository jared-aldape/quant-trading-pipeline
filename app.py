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

# IMPORT VIEWS
from src.interface import (
    view_live,          # Project Delta (Real-Time Execution)
    view_replay,        # The Gym (Fog of War Simulation)
    view_backtest,      # The Engine (Historical Validation)
    view_chart,         # Tactical Forensics (Deep Dive)
    view_stats,         # Performance Metrics
    view_predict,       # Future: Predictive Analysis
    view_growth,        # Future: Compound Calculators
    view_system_health  # System Diagnostics
)

# ==============================================================================
# 2. DYNAMIC ASSET COMPILATION (The Factory)
# ==============================================================================
def generate_logo_asset():
    """
    Generates the SVG Logo dynamically on startup using the version 
    defined in config.py. ensuring the 'Glass' always matches the 'Vault'.
    """
    # Defensive check for config version
    try:
        version_str = f"QUANT OS {config.SYSTEM_VERSION}"
    except AttributeError:
        version_str = "QUANT OS v3.3"

    # The Vector Blueprint (v3.3.1 - Stabilized Orbit)
    svg_content = f"""<svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg">
    <style>
        @keyframes radar-spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
        .orbit-group {{ transform-origin: 200px 200px; transform-box: view-box; animation: radar-spin 4s linear infinite; }}
        @keyframes core-pulse {{ 0% {{ stroke-opacity: 1; }} 50% {{ stroke-opacity: 0.5; }} 100% {{ stroke-opacity: 1; }} }}
        .core-node {{ animation: core-pulse 3s ease-in-out infinite; }}
    </style>
    <rect width="400" height="400" rx="40" fill="#0B0C10"/>
    <path d="M40 200H360" stroke="#1F2833" stroke-width="2"/>
    <path d="M200 40V360" stroke="#1F2833" stroke-width="2"/>
    <path d="M200 50 L329.9 125 V275 L200 350 L70.1 275 V125 L200 50 Z" stroke="#45A29E" stroke-width="8" stroke-linecap="round" fill="none"/>
    <path d="M200 80 L300 137 V263 L200 320 L100 263 V137 L140 114" stroke="#C5C6C7" stroke-width="4" stroke-linecap="round" stroke-dasharray="10 10"/>
    <circle class="core-node" cx="200" cy="200" r="30" fill="#1F2833" stroke="#66FCF1" stroke-width="4"/>
    <path d="M185 200 L200 215 L230 185" stroke="#66FCF1" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <g class="orbit-group"><rect x="195" y="40" width="10" height="20" fill="#FFA500"/></g>
    
    <text x="200" y="380" font-family="Courier New, monospace" font-weight="bold" font-size="24" fill="#C5C6C7" text-anchor="middle" letter-spacing="4">{version_str}</text>
</svg>"""

    # Ensure assets directory exists
    asset_path = ROOT_DIR / "assets"
    asset_path.mkdir(exist_ok=True)
    
    # Write the asset
    with open(asset_path / "quant_logo.svg", "w") as f:
        f.write(svg_content)

# EXECUTE ASSET GENERATION
generate_logo_asset()

# ==============================================================================
# 3. APP INITIALIZATION
# ==============================================================================
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.CYBORG], 
    suppress_callback_exceptions=True,
    title=f"Quant OS {getattr(config, 'SYSTEM_VERSION', 'v3.3')}" # Safe attribute access
)
server = app.server

# ==============================================================================
# 4. LAYOUT
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
                html.Small("SYSTEM STATUS", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("System Health", href="/health", active="exact"),
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                html.Small("PRESENT (EXECUTION)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Live Console", href="/live", active="exact"),
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                html.Small("PAST (ANALYSIS)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Data Generator", href="/backtest", active="exact"),
                dbc.NavLink("Chart Analysis", href="/chart", active="exact"),
                dbc.NavLink("Replay Analysis", href="/replay", active="exact"),
                dbc.NavLink("Statistics Lab", href="/stats", active="exact"),
                html.Hr(className="my-2", style={'opacity': '0.3'}),

                html.Small("FUTURE (FORECAST)", className="text-muted mt-2 mb-1 fw-bold"),
                dbc.NavLink("Predictive Analysis", href="/predict", active="exact"),
                dbc.NavLink("Growth Forecast", href="/growth", active="exact"),
                
            ], vertical=True, pills=True),
        ]),
        id="offcanvas",
        title="", # <--- FIXED: Title removed to eliminate obstruction
        is_open=False,
        style={"backgroundColor": "#0B0C10", "color": "white", "borderRight": "1px solid #1F2833"}
    ),
    
    html.Div(id='page-content', style={'padding': '20px', 'paddingTop': '80px'}),
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0)
])

# ==============================================================================
# 5. CALLBACKS
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
    if pathname == '/health' or pathname == '/': return view_system_health.render()
    elif pathname == '/live': return view_live.render()
    elif pathname == '/backtest': return view_backtest.render()
    elif pathname == '/chart': return view_chart.render()
    elif pathname == '/replay': return view_replay.render()
    elif pathname == '/stats': return view_stats.render()
    elif pathname == '/predict': return view_predict.render()
    elif pathname == '/growth': return view_growth.render()
    else: return view_system_health.render()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)