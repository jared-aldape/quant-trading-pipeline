import sys
import os
import dash
from dash import dcc, html, Input, Output, State, register_page, callback, ctx
import dash_bootstrap_components as dbc
import subprocess
import json
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# We are in: quant-trading-pipeline/src/tools/
# We need to reach: quant-trading-pipeline/ (Root)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Add Root to System Path to allow imports from 'src.utils'
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# ==============================================================================
# 2. SETUP
# ==============================================================================
register_page(__name__, path='/backtester', name='Backtester')
logger = get_logger("BacktestGUI")

# ==============================================================================
# 3. LAYOUT (Military Terminal Aesthetic)
# ==============================================================================
layout = dbc.Container([
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 1", className="text-muted mb-0"),
            html.H2("HISTORICAL BACKTESTER", className="display-6 fw-bold text-info"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    # CONTROLS
    dbc.Row([
        # LEFT COL: PARAMETERS
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("MISSION PARAMETERS", className="fw-bold text-warning"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Start Date"),
                            dbc.Input(id='bt-start-date', type='text', value='2024-01-01', className="mb-2")
                        ], width=6),
                        dbc.Col([
                            html.Label("End Date"),
                            dbc.Input(id='bt-end-date', type='text', value='2024-12-31', className="mb-2")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Start Balance ($)"),
                            dbc.Input(id='bt-balance', type='number', value=10000, className="mb-2")
                        ], width=6),
                        dbc.Col([
                            html.Label("Pos Size (%)"),
                            dbc.Input(id='bt-pos-size', type='number', value=0.5, step=0.1, className="mb-2")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Max Invest ($)"),
                            dbc.Input(id='bt-max-invest', type='number', value=5000, className="mb-2")
                        ], width=6),
                        dbc.Col([
                            html.Label("Enforce RTH"),
                            dbc.Checkbox(id='bt-rth', value=True, className="mt-4")
                        ], width=6)
                    ]),
                    html.Hr(),
                    dbc.Button("▶ RUN SIMULATION", id='bt-run-btn', color="info", className="w-100 fw-bold")
                ])
            ], className="shadow mb-3")
        ], width=12, md=4),

        # RIGHT COL: RESULTS
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("MISSION REPORT", className="fw-bold text-success"),
                dbc.CardBody([
                    html.Div(id='bt-results-area', children=[
                        html.P("Waiting for execution...", className="text-muted")
                    ])
                ], style={'minHeight': '300px'})
            ], className="shadow mb-3")
        ], width=12, md=8)
    ]),
    
    # LEDGER OUTPUT
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("TRADE LEDGER", className="fw-bold text-light"),
                dbc.CardBody([
                    dcc.Textarea(
                        id='bt-console-output',
                        value="",
                        style={'width': '100%', 'height': '200px', 'backgroundColor': '#000', 'color': '#0f0', 'fontFamily': 'monospace'},
                        readOnly=True
                    )
                ])
            ], className="shadow")
        ], width=12)
    ])

], fluid=True)

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    [Output('bt-results-area', 'children'), Output('bt-console-output', 'value')],
    [Input('bt-run-btn', 'n_clicks')],
    [State('bt-start-date', 'value'), State('bt-end-date', 'value'),
     State('bt-balance', 'value'), State('bt-pos-size', 'value'),
     State('bt-max-invest', 'value'), State('bt-rth', 'value')]
)
def run_backtest_engine(n_clicks, start_date, end_date, start_balance, pos_size, max_invest, rth_bool):
    if not n_clicks:
        return dash.no_update, "Ready."

    # 1. Locate the Engine Script (Robust Sibling Lookup)
    # We look for 10_backtest.py in the SAME folder as this script (src/tools/)
    engine_path = os.path.join(os.path.dirname(__file__), "10_backtest.py")
    
    if not os.path.exists(engine_path):
        return html.Div("❌ ERROR: Calculation Engine (10_backtest.py) not found.", className="text-danger"), ""

    # 2. Prepare Command
    cmd = [
        sys.executable, 
        engine_path,  # Absolute path to the engine
        "--start_date", str(start_date),
        "--end_date", str(end_date),
        "--start_balance", str(start_balance),
        "--pos_size_pct", str(pos_size),
        "--max_invest", str(max_invest),
        "--enforce_rth", str(rth_bool),
        "--archive_report", "True"
    ]
    
    # 3. Execute Subprocess
    # We pass os.environ to ensure PYTHONPATH from app.py is inherited
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
        
        # 4. Parse Output
        stdout = process.stdout
        stderr = process.stderr
        
        # Check for JSON Result in the stream
        json_marker = "JSON_RESULT:"
        if json_marker in stdout:
            # Split log from result
            raw_log, json_str = stdout.split(json_marker)
            result = json.loads(json_str)
            
            # Format Display
            res_display = html.Div([
                html.H4(f"Final Balance: ${result['final_balance']:,.2f}", className="text-success"),
                html.Hr(),
                dbc.Row([
                    dbc.Col(html.H5(f"Return: {result['total_return_pct']:.2f}%", className="text-info"), width=4),
                    dbc.Col(html.H5(f"Win Rate: {result['win_rate']:.1f}%", className="text-warning"), width=4),
                    dbc.Col(html.H5(f"Trades: {result['total_trades']}", className="text-light"), width=4),
                ])
            ])
            return res_display, raw_log
        else:
            # Fallback for errors
            err_display = html.Div([
                html.H4("Execution Failed", className="text-danger"),
                html.Pre(stderr if stderr else stdout)
            ])
            return err_display, stdout + "\n" + stderr

    except Exception as e:
        return html.Div(f"System Error: {str(e)}", className="text-danger"), str(e)