import dash
from dash import dcc, html, Input, Output, State, callback, register_page
import dash_bootstrap_components as dbc
import subprocess
import sys
import json
import logging
from datetime import datetime, date
from src.utils import config

register_page(__name__, path='/backtester', name='Backtester')

log = logging.getLogger("BackendGUI")

# --- UI HELPER ---
def get_status_ui(status_type, message=None):
    if status_type == "ready":
        return html.Div([
            html.Div("📊", className="display-4"),
            html.H4("Ready for Analysis", className="text-muted")
        ], className="text-center")
    elif status_type == "running":
        return html.Div([
            dbc.Spinner(color="primary", type="grow"),
            html.H4("Running Forensic Backtest...", className="text-primary mt-2")
        ], className="text-center")
    elif status_type == "success":
        return html.Div([
            html.Div("✅", className="display-4"),
            html.H4(message, className="text-success")
        ], className="text-center")
    elif status_type == "failure":
        return html.Div([
            html.Div("⚠️", className="display-4"),
            html.H4(message, className="text-warning")
        ], className="text-center")
    elif status_type == "crash":
        return html.Div([
            html.Div("💀", className="display-4"),
            html.H4("Execution Crash", style={"color": "#a855f7"})
        ], className="text-center")

# --- LAYOUT ---
layout = dbc.Container([
    
    # 1. CLEAN HEADER (No "Tool ID")
    dbc.Row([
        dbc.Col([
            html.H2("HISTORICAL BACKTESTER", className="display-6 fw-bold text-info"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    dbc.Row([
        # COLUMN 1: Inputs
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Historical Context"),
                dbc.CardBody([
                    html.Label("Backtest Period"),
                    dcc.DatePickerRange(
                        id='bt-date-range',
                        min_date_allowed=date(2020, 1, 1),
                        max_date_allowed=datetime.now().date(),
                        start_date=date(2025, 11, 1),
                        end_date=datetime.now().date(),
                        className="mb-3 w-100",
                    ),
                    dbc.Row([
                        dbc.Col([html.Label("Start Capital ($)"), dcc.Input(id='bt-start-balance', type='number', value=600.00, className="form-control")], width=6),
                        dbc.Col([html.Label("Position Size"), dcc.Input(id='bt-pos-size-display', value="75%", disabled=True, className="form-control")], width=6),
                    ], className="mb-2"),
                    dcc.Slider(id='bt-pos-size-slider', min=0.1, max=1.0, step=0.05, value=0.75, marks={0.1:'10%', 1.0:'100%'}, className="mb-3"),
                    dbc.Row([
                        dbc.Col([html.Label("Max Invest Cap ($)"), dcc.Input(id='bt-max-invest', type='number', value=5250.00, className="form-control")], width=6),
                        dbc.Col([html.Label("Tax Rate (1256)"), dcc.Input(id='bt-tax-rate', type='number', value=0.268, step=0.001, className="form-control")], width=6),
                    ]),
                    dbc.Checklist(options=[{"label": " Enforce RTH (9:30-4:00 EST)", "value": True}], value=[], id="bt-enforce-rth", switch=True, className="mt-3 text-warning"),
                ])
            ], className="mb-3 shadow"),
            
            dbc.Card([
                dbc.CardHeader("Risk Management"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([html.Label("ATR Sensitivity"), dcc.Input(id='bt-atr-sens', type='number', value=0.5, step=0.1, className="form-control")], width=6),
                        dbc.Col([html.Label("Trailing Stop (%)"), dcc.Input(id='bt-trail-pct', type='number', value=25, className="form-control")], width=6),
                    ]),
                ])
            ], className="mb-3 shadow"),
        ], width=12, lg=5),

        # COLUMN 2: Execution & Results
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Execution & Results"),
                dbc.CardBody([
                    dbc.Button("🚀 Run Forensic Analysis", id='bt-run-btn', color="primary", size="lg", className="w-100 mb-3"),
                    dbc.Checklist(options=[{"label": " Archive Report", "value": True}], value=[True], id="bt-archive-toggle", switch=True, className="mb-4 text-center text-info"),
                    html.Div(id='bt-status-area', children=get_status_ui("ready"), className="mb-4"),
                    dbc.Row([
                        dbc.Col([html.H6("Final Balance"), html.H3(id='bt-res-balance', children="--")]),
                        dbc.Col([html.H6("Net Return"), html.H3(id='bt-res-return', children="--")]),
                    ], className="text-center mb-3"),
                    dbc.Row([
                        dbc.Col([html.H6("Max Drawdown"), html.H4(id='bt-res-dd', children="--")]),
                        dbc.Col([html.H6("Win Rate"), html.H4(id='bt-res-win', children="--")]),
                    ], className="text-center"),
                    html.Div(id='bt-error-footer', className="text-center text-danger mt-3 fst-italic small")
                ])
            ], className="mb-3 shadow"),
            
            dbc.Card([
                dbc.CardHeader("Ledger Logs"),
                dbc.CardBody([
                    html.Pre(id='bt-log-output', children="Waiting...", style={'backgroundColor': '#0a0a0a', 'color': '#00ff41', 'padding': '15px', 'height': '200px', 'overflowY': 'scroll', 'fontSize': '12px', 'border': '1px solid #333'})
                ])
            ], className="mb-5 shadow"),
        ], width=12, lg=7)
    ])
], fluid=True)

# --- CALLBACKS ---
@callback(Output('bt-pos-size-display', 'value'), Input('bt-pos-size-slider', 'value'))
def update_label(val): return f"{int(val*100)}%"

@callback(
    [Output('bt-res-balance', 'children'), Output('bt-res-return', 'children'),
     Output('bt-res-dd', 'children'), Output('bt-res-win', 'children'),
     Output('bt-status-area', 'children'), Output('bt-error-footer', 'children'),
     Output('bt-log-output', 'children')],
    [Input('bt-run-btn', 'n_clicks')],
    [State('bt-date-range', 'start_date'), State('bt-date-range', 'end_date'),
     State('bt-start-balance', 'value'), State('bt-pos-size-slider', 'value'),
     State('bt-max-invest', 'value'), State('bt-tax-rate', 'value'),
     State('bt-enforce-rth', 'value'), State('bt-atr-sens', 'value'),
     State('bt-trail-pct', 'value'), State('bt-archive-toggle', 'value')]
)
def execute_simulation(n, start, end, bal, pos, max_inv, tax, rth, atr, trail, archive):
    if not n: return "--", "--", "--", "--", get_status_ui("ready"), "", "Waiting..."

    # Logic: Call 10_backtest.py from Root
    script_path = config.PROJECT_ROOT / "10_backtest.py"
    
    cmd = [
        sys.executable, str(script_path),
        "--start_date", str(start), "--end_date", str(end),
        "--start_balance", str(bal), "--pos_size_pct", str(pos),
        "--max_invest", str(max_inv), "--tax_rate", str(tax),
        "--atr_sensitivity", str(atr), "--trailing_stop_pct", str(trail / 100.0),
        "--enforce_rth", str(bool(rth)), "--archive_report", str(bool(archive)),
        "--stop_period_days", "9999", "--max_period_dd", "1.0"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=config.PROJECT_ROOT)
        full_output = result.stdout
        
        if "JSON_RESULT:" in full_output:
            log_text, json_text = full_output.split("JSON_RESULT:")
            json_data = json.loads(json_text)
        else:
            return "ERR", "ERR", "ERR", "ERR", get_status_ui("crash"), "No JSON", full_output

        formatted_logs = [html.Span(line + "\n", style={'color': '#ff5555'} if "SKIPPED" in line else {'color': '#00ff41'}) for line in log_text.splitlines()]

        if "error" in json_data:
             return "ERR", "ERR", "ERR", "ERR", get_status_ui("failure", "No Trades"), "", formatted_logs

        return (
            f"${json_data['final_balance']:,.2f}",
            html.Span(f"{json_data['total_return_pct']:+.1f}%", className="text-success" if json_data['total_return_pct'] > 0 else "text-danger"),
            html.Span(f"{json_data['max_drawdown_pct']:.1f}%", className="text-danger"),
            f"{json_data['win_rate']:.1f}%",
            get_status_ui("success", "Analysis Complete"), "", formatted_logs
        )
    except Exception as e:
        return "ERR", "ERR", "ERR", "ERR", get_status_ui("crash"), str(e), str(e)