import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
import pathlib
import sys

# ==============================================================================
# 1. SYSTEM PATH SETUP
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(ROOT_DIR))

# ==============================================================================
# 2. MODULE IMPORTS
# ==============================================================================
from src.interface import view_live_scope, view_options_sim, view_replay_analysis
from src.interface import view_chart_analysis, view_audit, view_rh_ledger
from src.interface import view_statistics, view_capital_growth
from src.interface import view_data_generator, view_rh_mirror, view_system_info
from src.interface import view_optimal_lab  # <--- NEW MODULE

# ==============================================================================
# 3. APP INITIALIZATION
# ==============================================================================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP], 
    suppress_callback_exceptions=True,
    title="MAGITEK OS",
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ]
)
server = app.server

# ==============================================================================
# 4. NAVIGATION CONTENT (Inside the Drawer)
# ==============================================================================
nav_content = html.Div([
    html.H2("MAGITEK OS", className="magitek-sidebar-header text-center"),
    html.Hr(style={"borderColor": "white"}),
    
    html.P("⚔️ BATTLE COMMAND", className="text-info small fw-bold mb-2", style={"font-family": "'VT323', monospace", "letter-spacing": "1px"}),
    dbc.Nav(
        [
            dbc.NavLink("⚡ ATB SCOPE", href="/scope", active="exact", className="fw-bold text-warning"),
            dbc.NavLink("⚔️ TRAINING", href="/sim", active="exact"),
            dbc.NavLink("📜 CHRONICLES", href="/replay", active="exact"),
        ], vertical=True, pills=True, className="mb-4"
    ),

    html.P("🔮 STRATEGY", className="text-info small fw-bold mb-2", style={"font-family": "'VT323', monospace", "letter-spacing": "1px"}),
    dbc.Nav(
        [
            dbc.NavLink("👁️ LIBRA SCAN", href="/chart", active="exact"),
            dbc.NavLink("🧪 OPTIMAL LAB", href="/lab", active="exact", className="text-success fw-bold"), # <--- NEW LINK
            dbc.NavLink("⚖️ JUDGMENT", href="/audit", active="exact"),
            dbc.NavLink("💰 GIL LEDGER", href="/ledger", active="exact"),
            dbc.NavLink("📊 JOB STATS", href="/stats", active="exact"),
            dbc.NavLink("📈 LEVEL UP", href="/growth", active="exact"),
        ], vertical=True, pills=True, className="mb-4"
    ),

    html.P("⚙️ ENGINE ROOM", className="text-info small fw-bold mb-2", style={"font-family": "'VT323', monospace", "letter-spacing": "1px"}),
    dbc.Nav(
        [
            dbc.NavLink("💎 SAVE CRYSTAL", href="/generator", active="exact", className="text-info"),
            dbc.NavLink("🎭 MIMIC", href="/mirror", active="exact"),
            dbc.NavLink("🩺 STATUS", href="/info", active="exact"),
        ], vertical=True, pills=True
    ),
])

# ==============================================================================
# 5. LAYOUT COMPONENTS
# ==============================================================================

# Floating Hamburger Button
menu_button = dbc.Button(
    "☰",
    id="btn_open_sidebar",
    n_clicks=0,
    className="btn btn-dark btn-lg",
    style={
        "position": "fixed",
        "top": "10px",
        "left": "10px",
        "z-index": "2000",  # Always on top
        "border-radius": "50%",
        "width": "50px",
        "height": "50px",
        "opacity": "0.8",
        "box-shadow": "0px 0px 10px rgba(0,0,0,0.5)"
    }
)

# The Slide-Out Drawer (Offcanvas)
sidebar_drawer = dbc.Offcanvas(
    nav_content,
    id="sidebar_drawer",
    is_open=False,
    placement="start",  # Slides in from the left
    style={
        "background-color": "#283878", 
        "color": "white",
        "border-right": "4px solid #b5b8b9"
    }
)

# Main Content Area (Full Width)
content = html.Div(
    id="page-content", 
    style={
        "padding": "1rem", 
        "background-color": "#000000",
        "min-height": "100vh",
        "padding-top": "4rem"  # Space for the floating button at the top
    }
)

app.layout = html.Div([
    dcc.Location(id="url"),
    menu_button,
    sidebar_drawer,
    content
])

# ==============================================================================
# 6. CALLBACKS
# ==============================================================================

# Toggle Sidebar Logic (Handles Button Click AND Navigation)
@app.callback(
    Output("sidebar_drawer", "is_open"),
    [Input("btn_open_sidebar", "n_clicks"),
     Input("url", "pathname")],  # Added URL as input
    [State("sidebar_drawer", "is_open")],
)
def manage_sidebar(n_clicks, pathname, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # If button clicked, toggle
    if trigger_id == 'btn_open_sidebar':
        return not is_open
    
    # If URL changed (navigation), force close
    if trigger_id == 'url':
        return False
        
    return is_open

# Page Routing Logic
@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/" or pathname == "/info": return view_system_info.render()
    elif pathname == "/scope": return view_live_scope.render()
    elif pathname == "/sim": return view_options_sim.render()
    elif pathname == "/replay": return view_replay_analysis.render()
    elif pathname == "/chart": return view_chart_analysis.render()
    elif pathname == "/lab": return view_optimal_lab.render()  # <--- NEW ROUTE
    elif pathname == "/audit": return view_audit.render()
    elif pathname == "/ledger": return view_rh_ledger.render()
    elif pathname == "/stats": return view_statistics.render()
    elif pathname == "/growth": return view_capital_growth.render()
    elif pathname == "/generator": return view_data_generator.render()
    elif pathname == "/mirror": return view_rh_mirror.render()
    
    return html.Div(
        dbc.Container([
            html.H1("ZONE: THE VOID", className="text-danger magitek-h2"),
            html.P(f"Coordinates {pathname} unknown.", className="magitek-note"),
        ], className="py-5 text-center")
    )

if __name__ == "__main__":
    print("🚀 MAGITEK ENGINE START...")
    app.run(host='0.0.0.0', debug=True, port=8050)