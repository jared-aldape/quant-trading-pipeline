import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
import pathlib
import sys
import threading

# ==============================================================================
# 1. SYSTEM PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).parent.resolve()
sys.path.append(str(ROOT_DIR))

# ==============================================================================
# 2. MODULE IMPORTS (The Institutional 12)
# ==============================================================================
from src.interface import view_live_scope, view_options_sim, view_replay_analysis
from src.interface import view_chart_analysis, view_audit, view_rh_ledger
from src.interface import view_statistics, view_capital_growth
from src.interface import view_data_generator, view_rh_mirror, view_system_info
from src.interface import view_optimal_lab 

# BACKGROUND ENGINE (Root Level Import)
try:
    import main_pipeline
except ImportError:
    main_pipeline = None

# ==============================================================================
# 3. APP INITIALIZATION
# ==============================================================================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP], 
    suppress_callback_exceptions=True,
    title="QUANT OS | INSTITUTIONAL TERMINAL",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ==============================================================================
# 4. INSTITUTIONAL STYLING
# ==============================================================================
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "19rem",
    "padding": "2rem 1rem",
    "backgroundColor": "#0f172a", # Midnight Blue
    "color": "#f8fafc",
    "borderRight": "1px solid #334155",
    "overflowY": "auto"
}

CONTENT_STYLE = {
    "marginLeft": "19rem",
    "padding": "2rem",
    "backgroundColor": "#020617", # Deepest Blue/Black
    "minHeight": "100vh",
    "color": "#f8fafc"
}

SECTION_HEADER_STYLE = {
    "color": "#94a3b8",
    "fontSize": "0.75rem",
    "fontWeight": "bold",
    "letterSpacing": "1.5px",
    "marginTop": "1.5rem",
    "marginBottom": "0.5rem",
    "paddingLeft": "0.5rem",
    "borderBottom": "1px solid #334155"
}

# ==============================================================================
# 5. LAYOUT ARCHITECTURE
# ==============================================================================
sidebar = html.Div(
    [
        html.H2("QUANT OS", className="display-6 fw-bold text-white mb-0", style={"letterSpacing": "2px"}),
        html.Div("INSTITUTIONAL TERMINAL", className="text-muted small font-monospace mb-4"),
        
        # --- OPERATIONS (Real-Time & Sim) ---
        html.Div("OPERATIONS", style=SECTION_HEADER_STYLE),
        dbc.Nav(
            [
                dbc.NavLink("LIVE SCOPE", href="/scope", active="exact", className="fw-bold font-monospace py-1"),
                dbc.NavLink("OPTIONS SIMULATOR", href="/sim", active="exact", className="fw-bold font-monospace py-1"),
                dbc.NavLink("REPLAY ANALYSIS", href="/replay", active="exact", className="fw-bold font-monospace py-1"),
            ], vertical=True, pills=True,
        ),

        # --- ANALYTICS (Research & Patterns) ---
        html.Div("ANALYTICS & STRATEGY", style=SECTION_HEADER_STYLE),
        dbc.Nav(
            [
                dbc.NavLink("CHART SCANNER", href="/chart", active="exact", className="fw-bold font-monospace py-1"),
                dbc.NavLink("OPTIMAL LAB", href="/lab", active="exact", className="fw-bold font-monospace py-1"),
                
                # Companion Tools
                dbc.NavLink("TRADE AUDIT & PATTERNS", href="/audit", active="exact", className="fw-bold font-monospace py-1 text-info"),
                dbc.NavLink("STATISTICAL METRICS", href="/stats", active="exact", className="fw-bold font-monospace py-1 text-info"),
                
                dbc.NavLink("RH LEDGER", href="/ledger", active="exact", className="fw-bold font-monospace py-1"),
                dbc.NavLink("CAPITAL GROWTH", href="/growth", active="exact", className="fw-bold font-monospace py-1"),
            ], vertical=True, pills=True,
        ),

        # --- INFRASTRUCTURE (System & Config) ---
        html.Div("SYSTEM INFRASTRUCTURE", style=SECTION_HEADER_STYLE),
        dbc.Nav(
            [
                dbc.NavLink("BACKTEST SEQUENCER", href="/generator", active="exact", className="fw-bold font-monospace py-1"),
                dbc.NavLink("RH MIRROR", href="/mirror", active="exact", className="fw-bold font-monospace py-1"),
                dbc.NavLink("SYSTEM MONITOR", href="/info", active="exact", className="fw-bold font-monospace py-1"),
            ], vertical=True, pills=True,
        ),

        html.Div([
            html.Hr(className="border-secondary"),
            html.Small("v4.0.9 STRUCTURED", className="text-muted font-monospace")
        ], style={"marginTop": "auto", "paddingTop": "20px"})
    ],
    style=SIDEBAR_STYLE,
)

content = html.Div(id="page-content", style=CONTENT_STYLE)

app.layout = html.Div([dcc.Location(id="url"), sidebar, content])

# ==============================================================================
# 6. ROUTER CALLBACKS
# ==============================================================================
@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/" or pathname == "/info": return view_system_info.render()
    elif pathname == "/scope": return view_live_scope.render()
    elif pathname == "/sim": return view_options_sim.render()
    elif pathname == "/replay": return view_replay_analysis.render()
    elif pathname == "/chart": return view_chart_analysis.render()
    elif pathname == "/lab": return view_optimal_lab.render()
    elif pathname == "/audit": return view_audit.render()
    elif pathname == "/ledger": return view_rh_ledger.render()
    elif pathname == "/stats": return view_statistics.render()
    elif pathname == "/growth": return view_capital_growth.render()
    elif pathname == "/generator": return view_data_generator.render()
    elif pathname == "/mirror": return view_rh_mirror.render()
    
    return html.Div(
        dbc.Container([
            html.H1("404: OBJECT NOT FOUND", className="text-danger fw-bold font-monospace"),
            html.P(f"Route {pathname} does not exist in the institutional registry.", className="text-muted font-monospace"),
        ], className="py-5 text-center")
    )

# ==============================================================================
# 7. MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    print("🚀 QUANT OS INSTITUTIONAL TERMINAL BOOTING...")
    
    # ⚡ MANUAL MODE: BACKGROUND THREAD DISABLED FOR DEBUGGING
    # To re-enable auto-downloads, uncomment the lines below.
    
    # if main_pipeline:
    #     try:
    #         t = threading.Thread(target=main_pipeline.run_continuous_cycle)
    #         t.daemon = True
    #         t.start()
    #         print("✅ BACKGROUND PIPELINE INITIATED")
    #     except Exception as e:
    #         print(f"⚠️ PIPELINE START FAILED: {e}")
    
    # ⚡ DASH 2.0 STARTUP
    app.run(debug=True, use_reloader=True, port=8050)