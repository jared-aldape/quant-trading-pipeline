import dash
from dash import html, dcc, register_page
import dash_bootstrap_components as dbc
from src.utils import config
import os

register_page(__name__, path='/', name='Home')

def get_db_status():
    if config.DB_FILE.exists():
        size_mb = os.path.getsize(config.DB_FILE) / (1024 * 1024)
        return f"CONNECTED ({size_mb:.1f} MB)"
    return "DISCONNECTED"

layout = dbc.Container([
    html.H1("System Status", className="mb-4"),
    
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Market Data Vault"),
            dbc.CardBody([
                html.H3(get_db_status(), className="text-success"),
                html.P(f"Path: {config.DB_FILE}", className="text-muted small")
            ])
        ], color="dark", inverse=True, className="mb-3"), width=12, md=6),
        
        dbc.Col(dbc.Card([
            dbc.CardHeader("Pipeline Config"),
            dbc.CardBody([
                html.P(f"Timezone: {config.TZ_LOCAL}"),
                html.P(f"Reports: {config.REPORTS_DIR}"),
            ])
        ], color="dark", inverse=True, className="mb-3"), width=12, md=6),
    ]),
    
    html.Hr(),
    html.H3("Select a Tool from the Sidebar to Begin.", className="text-info")
], fluid=True)