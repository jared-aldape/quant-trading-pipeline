import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import pathlib
import sys

# ==============================================================================
# 1. SYSTEM PATH SETUP
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).parent
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ==============================================================================
# 2. MODULE IMPORTS
# ==============================================================================
from src.interface import view_live_scope, view_options_sim, view_replay_analysis
from src.interface import view_chart_analysis, view_audit, view_rh_ledger
from src.interface import view_statistics, view_capital_growth
from src.interface import view_data_generator, view_rh_mirror, view_system_info

# ==============================================================================
# 3. APP INITIALIZATION
# ==============================================================================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP], 
    suppress_callback_exceptions=True,
    title="MAGITEK OS"
)
server = app.server

# ==============================================================================
# 4. WORLD MAP (SIDEBAR)
# ==============================================================================
sidebar = html.Div(
    [
        html.H2("MAGITEK OS", className="magitek-sidebar-header"),
        html.Hr(style={"borderColor": "white"}),
        
        html.P("⚔️ BATTLE COMMAND", className="text-info small fw-bold mb-2", style={"font-family": "'VT323', monospace", "letter-spacing": "1px"}),
        dbc.Nav(
            [
                dbc.NavLink("⚡ ATB SCOPE", href="/scope", active="exact", className="fw-bold text-warning"),
                dbc.NavLink("⚔️ TRAINING GROUNDS", href="/sim", active="exact"),
                dbc.NavLink("📜 CHRONICLES", href="/replay", active="exact"),
            ], vertical=True, pills=True, className="mb-4"
        ),

        html.P("🔮 STRATEGY", className="text-info small fw-bold mb-2", style={"font-family": "'VT323', monospace", "letter-spacing": "1px"}),
        dbc.Nav(
            [
                dbc.NavLink("👁️ LIBRA SCAN", href="/chart", active="exact"),
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
    ],
    style={
        "position": "fixed", "top": 0, "left": 0, "bottom": 0,
        "width": "18rem", "padding": "2rem 1rem",
        "background-color": "#283878", 
        "border-right": "4px solid #b5b8b9",
        "box-shadow": "inset -2px 0 10px rgba(0,0,0,0.5)",
        "overflow-y": "auto",
        "z-index": 1000
    },
)

content = html.Div(id="page-content", style={
    "margin-left": "20rem", 
    "margin-right": "2rem", 
    "padding": "2rem 1rem",
    "background-color": "#000000",
    "min-height": "100vh"
})

app.layout = html.Div([dcc.Location(id="url"), sidebar, content])

# ==============================================================================
# 5. ROUTING LOGIC
# ==============================================================================
@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/" or pathname == "/scope": return view_live_scope.render()
    elif pathname == "/sim": return view_options_sim.render()
    elif pathname == "/replay": return view_replay_analysis.render()
    elif pathname == "/chart": return view_chart_analysis.render()
    elif pathname == "/audit": return view_audit.render()
    elif pathname == "/ledger": return view_rh_ledger.render()
    elif pathname == "/stats": return view_statistics.render()
    elif pathname == "/growth": return view_capital_growth.render()
    elif pathname == "/generator": return view_data_generator.render()
    elif pathname == "/mirror": return view_rh_mirror.render()
    elif pathname == "/info": return view_system_info.render()
    
    return html.Div(
        dbc.Container([
            html.H1("ZONE: THE VOID", className="text-danger magitek-h2"),
            html.P(f"Coordinates {pathname} unknown.", className="magitek-note"),
        ], className="py-5 text-center")
    )

if __name__ == "__main__":
    print("🚀 MAGITEK ENGINE START...")
    app.run(debug=True, port=8050)