import sys
import os
import dash
from dash import dcc, html, register_page
import dash_bootstrap_components as dbc
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# Ensures imports work when run from app.py
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

# ==============================================================================
# 2. MPA PAGE REGISTRATION
# ==============================================================================
register_page(
    __name__, 
    path='/', 
    name='Home', 
    title='Quant OS // Command Terminal'
)

# ==============================================================================
# 3. LAYOUT (Military Terminal Welcome)
# ==============================================================================
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H1("QUANT OS V2.2 // READY FOR EXECUTION", 
                    className="display-3 fw-bold mt-5", 
                    style={'color': '#00ff00', 'textShadow': '0px 0px 5px #00ff00'}),
            html.Hr(style={'borderColor': '#333'}),
            html.P([
                "System Operational. Data streams verified and compliant with ",
                html.Span("The Timezone Law (UTC in Vault).", className="text-warning fw-bold"),
            ], className="lead text-light mb-4"),
            
            html.P(
                "Please select a tool from the sidebar menu to begin analysis, simulation, or live monitoring.",
                className="text-info fst-italic"
            ),

            # Status Box
            dbc.Card([
                dbc.CardBody(html.H5("STATUS: SIDE MENU NAVIGATION ACTIVE", className="text-center text-success mb-0"))
            ], color="#1a1a1a", className="mt-5 border-success")
            
        ], width=12)
    ])
], fluid=True, style={'fontFamily': 'monospace'})