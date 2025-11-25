import dash
from dash import html, dcc
import dash_bootstrap_components as dbc

# Initialize Quant OS with Dark Theme (Cyborg) & Mobile Responsiveness
app = dash.Dash(
    __name__, 
    use_pages=True, 
    external_stylesheets=[dbc.themes.CYBORG],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ==========================================
# 1. DESKTOP SIDEBAR (Visible on PC)
# ==========================================
sidebar = html.Div(
    [
        html.H2("QUANT OS", className="display-5 fw-bold"),
        html.Hr(),
        html.P("v2.0 | UTC Vault", className="lead fs-6 text-muted"),
        dbc.Nav(
            [
                dbc.NavLink("🏠 Home", href="/", active="exact"),
                dbc.NavLink("1. Backtester", href="/backtester", active="exact"),
                dbc.NavLink("2. Forecaster", href="/forecaster", active="exact"),
                dbc.NavLink("3. Analysis", href="/analysis", active="exact"),
                dbc.NavLink("4. Simulator", href="/simulator", active="exact"),
                dbc.NavLink("5. Live Ops", href="/live", active="exact"),
                dbc.NavLink("6. Periscope", href="/periscope", active="exact"),
            ],
            vertical=True,
            pills=True,
            className="fs-5"
        ),
        html.Hr(),
        html.Div([
             html.Small("Status: ", className="text-muted"),
             html.Span("ONLINE", className="text-success fw-bold")
        ], className="mt-auto")
    ],
    style={
        "position": "fixed", "top": 0, "left": 0, "bottom": 0,
        "width": "16rem", "padding": "2rem 1rem", 
        "backgroundColor": "#050505", "borderRight": "1px solid #333",
        "zIndex": 1000
    },
    className="d-none d-md-block" # CSS: Hide on mobile, show on desktop
)

# ==========================================
# 2. MOBILE HEADER (Visible on Phone)
# ==========================================
mobile_header = dbc.NavbarSimple(
    brand="QUANT OS v2.0",
    brand_href="/",
    color="dark",
    dark=True,
    children=[
        dbc.NavItem(dbc.NavLink("1. Backtester", href="/backtester")),
        dbc.NavItem(dbc.NavLink("2. Forecaster", href="/forecaster")),
        dbc.NavItem(dbc.NavLink("3. Analysis", href="/analysis")),
        dbc.NavItem(dbc.NavLink("4. Simulator", href="/simulator")),
        dbc.NavItem(dbc.NavLink("5. Live Ops", href="/live")),
        dbc.NavItem(dbc.NavLink("6. Periscope", href="/periscope")),
    ],
    className="d-md-none mb-3" # CSS: Hide on desktop, show on mobile
)

# ==========================================
# 3. APP LAYOUT SHELL
# ==========================================
app.layout = html.Div([
    dcc.Location(id="url"),
    sidebar,
    # The 'content-responsive' class (in assets/style.css) handles the margins
    html.Div([
        mobile_header,
        dash.page_container
    ], className="content-responsive")
])

# ==========================================
# 4. EXECUTION
# ==========================================
if __name__ == "__main__":
    # Host 0.0.0.0 allows access from other devices (like your Pixel) on the network
    app.run(debug=True, host='0.0.0.0', port=8080)