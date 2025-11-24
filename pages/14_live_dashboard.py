import dash
from dash import dcc, html, Input, Output, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from datetime import datetime
import pytz

# Register as "Live Ops" in the Master Launcher
register_page(__name__, path='/live', name='Live Ops')

# Timezone Law: Local on the Glass
TZ_LOCAL = pytz.timezone('US/Pacific')

# ==========================================
# LAYOUT: "The Cockpit"
# ==========================================
layout = dbc.Container([
    
    # --- HEADER ---
    dbc.Row([
        dbc.Col([
            html.H2(["🔴 Live Operations Center"], className="text-danger fw-bold"),
            html.P("Real-Time Execution & Monitoring (Tool 5)", className="text-muted")
        ], width=8),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H5("MARKET STATUS", className="text-muted small mb-0"),
                    html.H3("STANDBY", className="text-warning", id="market-status-text")
                ], className="p-2 text-center")
            ], color="dark", outline=True)
        ], width=4)
    ], className="mt-4 mb-3"),

    # --- MAIN DASHBOARD (Mimics Analysis Layout) ---
    dbc.Row([
        # LEFT: The Chart (65%)
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-graph-up me-2"),
                    "Intraday Price Action (SPX vs Option)"
                ]),
                dbc.CardBody([
                    dcc.Graph(
                        id='live-chart',
                        figure=go.Figure(layout=dict(
                            template='plotly_dark',
                            height=600,
                            title="Waiting for Data Feed...",
                            xaxis=dict(showgrid=False),
                            yaxis=dict(showgrid=False)
                        )),
                        config={'displayModeBar': False}
                    )
                ], className="p-0")
            ], className="shadow mb-4")
        ], width=12, lg=8),

        # RIGHT: The Telemetry (35%)
        dbc.Col([
            # 1. Target Lock
            dbc.Card([
                dbc.CardHeader("🎯 Target Acquisition"),
                dbc.CardBody([
                    html.Label("Projected ATM Strike", className="text-info"),
                    html.H2("----", id='live-strike', className="text-white"),
                    html.Hr(),
                    dbc.Row([
                        dbc.Col([html.Small("Delta"), html.H5("--", className="text-muted")]),
                        dbc.Col([html.Small("Gamma"), html.H5("--", className="text-muted")]),
                        dbc.Col([html.Small("IV%"), html.H5("--", className="text-muted")]),
                    ])
                ])
            ], className="mb-3"),

            # 2. P&L Engine
            dbc.Card([
                dbc.CardHeader("💰 Session P&L"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([html.H6("Unrealized"), html.H3("$0.00", className="text-muted")], width=6),
                        dbc.Col([html.H6("Return"), html.H3("0.00%", className="text-muted")], width=6),
                    ]),
                    dbc.Progress(value=0, className="mt-3", style={"height": "5px"})
                ])
            ], className="mb-3"),

            # 3. Controls
            dbc.Card([
                dbc.CardHeader("⚙️ Execution Controls"),
                dbc.CardBody([
                    dbc.Button("⚠️ EMERGENCY FLATTEN", color="danger", outline=True, size="lg", className="w-100 mb-2", disabled=True),
                    dbc.Button("Force Refresh", color="secondary", size="sm", className="w-100")
                ])
            ])
        ], width=12, lg=4)
    ]),

    # --- TICKER (Heartbeat) ---
    dcc.Interval(id='live-interval', interval=2000, n_intervals=0)

], fluid=True)

# ==========================================
# LOGIC
# ==========================================
@callback(
    Output('market-status-text', 'children'),
    Input('live-interval', 'n_intervals')
)
def update_heartbeat(n):
    # Simple clock logic to simulate "Awareness"
    now = datetime.now(TZ_LOCAL)
    return now.strftime("%H:%M:%S PST")