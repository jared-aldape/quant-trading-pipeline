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

# --- THE SIDEBAR (Navigation) ---
sidebar = html.Div(
    [
        html.H2("QUANT OS", className="display-5 fw-bold"),
        html.Hr(),
        html.P("v2.0 | UTC Vault", className="lead fs-6 text-muted"),
        dbc.Nav(
            [
                dbc.NavLink("🏠 Home", href="/", active="exact"),
                dbc.NavLink("📉 Backtester", href="/backtester", active="exact"),
                dbc.NavLink("🔮 Forecaster", href="/forecaster", active="exact"),
                dbc.NavLink("🕵️ Analysis", href="/analysis", active="exact"),
                dbc.NavLink("🕹️ Simulator", href="/simulator", active="exact"),
                dbc.NavLink("🔴 Live Ops", href="/live", active="exact"),
                dbc.NavLink("🔭 Periscope", href="/periscope", active="exact"),
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
    className="d-none d-md-block" # Hide on mobile, show on desktop
)

# --- MOBILE HEADER (Visible only on XS/SM screens) ---
mobile_header = dbc.NavbarSimple(
    brand="QUANT OS v2.0",
    brand_href="/",
    color="dark",
    dark=True,
    children=[
        dbc.NavItem(dbc.NavLink("Backtester", href="/backtester")),
        dbc.NavItem(dbc.NavLink("Live Ops", href="/live")),
        dbc.NavItem(dbc.NavLink("Periscope", href="/periscope")),
    ],
    className="d-md-none mb-3"
)

# --- CONTENT AREA ---
content = html.Div(
    dash.page_container,
    style={"padding": "2rem"},
    className="ms-md-64" 
)

# Desktop Content Margin
desktop_content_style = {"marginLeft": "16rem", "padding": "2rem"}
# Mobile Content Margin
mobile_content_style = {"padding": "1rem"}

app.layout = html.Div([
    dcc.Location(id="url"),
    sidebar,
    html.Div([
        mobile_header,
        dash.page_container
    ], style=desktop_content_style, className="content-responsive")
])

if __name__ == "__main__":
    # Host 0.0.0.0 enables LAN access for Mobile PWA testing
    # Port 8080 is the standard port for the Master Launcher
    app.run(debug=True, host='0.0.0.0', port=8080)