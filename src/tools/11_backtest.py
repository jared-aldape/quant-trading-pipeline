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
from datetime import date, datetime, timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

logger = get_logger("BacktestGUI")

# ==============================================================================
# 2. MPA PAGE REGISTRATION
# ==============================================================================
register_page(__name__, path='/backtester', name='Backtester')

# ==============================================================================
# 3. HELPER UI & DEFAULTS
# ==============================================================================
today = date.today()
default_start = (today - timedelta(days=45)).strftime("%Y-%m-%d")
default_end = today.strftime("%Y-%m-%d")

def get_status_ui(status_type, message=None):
    if status_type == "ready":
        return html.Div([html.Div("📊", className="display-4"), html.H4("Ready for Analysis", className="text-muted")], className="text-center")
    elif status_type == "running":
        return html.Div([dbc.Spinner(color="primary", type="grow"), html.H4("Running Forensic Backtest...", className="text-primary mt-2")], className="text-center")
    elif status_type == "success":
        return html.Div([html.Div("✅", className="display-4"), html.H4(message, className="text-success")], className="text-center")
    elif status_type == "failure":
        return html.Div([html.Div("⚠️", className="display-4"), html.H4(message, className="text-warning")], className="text-center")
    elif status_type == "crash":
        return html.Div([html.Div("💀", className="display-4"), html.H4("Execution Crash", style={"color": "#a855f7"})], className="text-center")

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
layout = dbc.Container([
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 1", className="text-muted mb-0"),
            html.H2("HISTORICAL BACKTESTER (REAL DATA)", className="display-6 fw-bold text-info"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    # CONTROLS
    dbc.Row([
        # COLUMN 1: Inputs
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("MISSION PARAMETERS", className="fw-bold text-warning"),
                dbc.CardBody([
                    html.Label("Backtest Period"),
                    dcc.DatePickerRange(
                        id='bt-date-range',
                        min_date_allowed=date(2020, 1, 1),
                        max_date_allowed=today,
                        start_date=default_start,
                        end_date=today,
                        className="mb-3 w-100",
                    ),
                    
                    dbc.Row([
                        dbc.Col([
                            html.Label("Start Capital ($)"),
                            dbc.Input(id='bt-balance', type='number', value=600, className="mb-2")
                        ], width=6),
                        dbc.Col([
                            html.Label("Pos Size (%)"),
                            dbc.Input(id='bt-pos-size', type='number', value=75, step=0.1, className="mb-2")
                        ], width=6)
                    ]),
                    
                    dbc.Row([
                        dbc.Col([
                            html.Label("Max Invest ($)"),
                            dbc.Input(id='bt-max-invest', type='number', value=5000, className="mb-2")
                        ], width=6),
                        dbc.Col([
                            html.Label("Tax Rate (1256)"), 
                            dbc.Input(id='bt-tax-rate', type='number', value=0.268, step=0.001, className="mb-2")
                        ], width=6)
                    ]),
                    
                    html.Hr(className="my-2"),
                    
                    # STRATEGY SELECTION
                    dbc.Row([
                        dbc.Col([
                            html.Label("Execution Strategy"),
                            dcc.Dropdown(
                                id='bt-selection-mode',
                                options=[
                                    {'label': 'Standard (First Signal)', 'value': 'FIRST'},
                                    {'label': 'Optimized (Best Signal)', 'value': 'BEST'}
                                ],
                                value='FIRST',
                                clearable=False,
                                className="mb-2",
                                style={'color': '#000000'}
                            ),
                        ], width=6),
                        dbc.Col([
                            html.Label("Strike Selection"),
                             dcc.Dropdown(
                                id='bt-strike-offset',
                                options=[
                                    {'label': 'Deep ITM (-2)', 'value': -2},
                                    {'label': 'ITM (-1)', 'value': -1},
                                    {'label': 'ATM (Default)', 'value': 0},
                                    {'label': 'OTM (+1)', 'value': 1},
                                    {'label': 'Deep OTM (+2)', 'value': 2},
                                ],
                                value=0,
                                clearable=False,
                                className="mb-2",
                                style={'color': '#000000'}
                            ),
                        ], width=6)
                    ]),

                    dbc.Checklist(options=[{"label": " Enforce RTH (9:30-4:00 EST)", "value": True}], value=[True], id="bt-rth", switch=True, className="mt-2 text-warning"),
                    html.Hr(),
                    dbc.Button("▶ RUN SIMULATION", id='bt-run-btn', color="info", className="w-100 fw-bold")
                ])
            ], className="shadow mb-3"),
            
            dbc.Card([
                dbc.CardHeader("Risk Management (On Premium)"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Trailing Stop (%)"),
                            dbc.Input(id='bt-trail-pct', type='number', value=25, className="form-control")
                        ], width=6),
                        dbc.Col([
                            html.Label("Ideal Gain (%)"),
                            dbc.Input(id='bt-ideal-gain', type='number', value=40, className="form-control")
                        ], width=6),
                    ]),
                    html.Small("Stops applied directly to Option Price (e.g., $2.00 -> $1.50)", className="text-muted mt-2 d-block")
                ])
            ], className="mb-3 shadow"),
            
        ], width=12, md=4),

        # COLUMN 2: Execution & Results
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("EQUITY CURVE", className="fw-bold text-primary"),
                dbc.CardBody([
                    dcc.Graph(id='bt-equity-chart', style={'height': '350px'}, config={'displayModeBar': False}),
                    html.Div(id='bt-status-area', children=get_status_ui("ready"), className="mb-4 mt-3"),
                ], style={'padding': '10px'})
            ], className="mb-3 shadow"),

            dbc.Card([
                dbc.CardHeader("REPORT SUMMARY", className="fw-bold text-success"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([html.H6("Final Balance"), html.H3(id='bt-res-balance', children="--")], className="text-center"),
                        dbc.Col([html.H6("Net Return"), html.H3(id='bt-res-return', children="--")], className="text-center"),
                    ], className="text-center mb-3"),
                    dbc.Row([
                        dbc.Col([html.H6("Max Drawdown"), html.H4(id='bt-res-dd', children="--")], className="text-center"),
                        dbc.Col([html.H6("Win Rate"), html.H4(id='bt-res-win', children="--")], className="text-center"),
                    ]),
                    html.Div(id='bt-error-footer', className="text-center text-danger mt-3 fst-italic small")
                ])
            ], className="mb-3 shadow"),

        ], width=12, lg=7)
    ]),
    
    # LEDGER OUTPUT ROW
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("LEDGER LOGS (Detailed Trades)", className="fw-bold text-light"),
                dbc.CardBody([
                    html.Div(id='bt-trade-table'),
                    
                    html.Pre(id='bt-log-output', children="Waiting...", style={'backgroundColor': '#0a0a0a', 'color': '#00ff41', 'padding': '15px', 'height': '200px', 'overflowY': 'scroll', 'fontSize': '12px', 'border': '1px solid #333', 'marginTop': '10px'})
                ])
            ], className="mb-5 shadow")
        ], width=12)
    ])

], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
def generate_trade_table(dates, tickers, entries, exits, reasons, pnl_values, returns_values):
    table_rows = []
    
    for d, tick, ent, ex, rsn, pnl, ret in zip(dates, tickers, entries, exits, reasons, pnl_values, returns_values):
        is_win = pnl >= 0
        pnl_text = f"{'+' if is_win else ''}${pnl:,.2f}"
        ret_text = f"{ret*100:+.1f}%"
        
        row_style = {'backgroundColor': 'rgba(0, 255, 65, 0.1)'} if is_win else {'backgroundColor': 'rgba(255, 0, 0, 0.1)'}
        text_color = '#00ff41' if is_win else '#ff5555'
        
        clean_ticker = tick.replace("O:", "")
        
        table_rows.append(html.Tr([
            html.Td(d, className="text-white small"),
            html.Td(clean_ticker, className="text-info small", style={'fontFamily': 'monospace'}),
            html.Td(f"${ent:.2f}", className="text-light small"),
            html.Td(f"${ex:.2f}", className="text-light small"),
            html.Td(rsn, className="text-warning small fst-italic"),
            html.Td(pnl_text, style={'color': text_color, 'fontWeight': 'bold'}),
            html.Td(ret_text, style={'color': text_color}),
        ], style=row_style))

    return dbc.Table(
        [html.Thead(html.Tr([
            html.Th("Date/Time"), 
            html.Th("Ticker"), 
            html.Th("Entry"), 
            html.Th("Exit"), 
            html.Th("Rslt"), 
            html.Th("Net P&L"), 
            html.Th("ROI")
        ]))] +
        [html.Tbody(table_rows)],
        bordered=False, hover=True, size="sm", className="text-white", style={'fontSize': '12px'}
    )

@callback(
    [Output('bt-res-balance', 'children'), Output('bt-res-return', 'children'),
     Output('bt-res-dd', 'children'), Output('bt-res-win', 'children'),
     Output('bt-status-area', 'children'), Output('bt-error-footer', 'children'),
     Output('bt-log-output', 'children'), Output('bt-equity-chart', 'figure'),
     Output('bt-trade-table', 'children')],
    [Input('bt-run-btn', 'n_clicks')],
    [State('bt-date-range', 'start_date'), State('bt-date-range', 'end_date'),
     State('bt-balance', 'value'), 
     State('bt-pos-size', 'value'),
     State('bt-max-invest', 'value'), 
     State('bt-tax-rate', 'value'), 
     State('bt-rth', 'value'), 
     State('bt-trail-pct', 'value'),
     State('bt-selection-mode', 'value'),
     State('bt-strike-offset', 'value'), 
     State('bt-ideal-gain', 'value')] 
)
def run_backtest_engine(n_clicks, start_date, end_date, start_balance, pos_size, max_invest, tax_rate, rth_value, trail_pct, selection_mode, strike_offset, ideal_gain):
    if not n_clicks:
        return "--", "--", "--", "--", get_status_ui("ready"), "", "Waiting...", go.Figure(), None 

    ideal_gain_val = ideal_gain if ideal_gain else 0.0
    strike_offset_val = strike_offset if strike_offset else 0
    
    current_dir = Path(__file__).resolve().parent
    engine_path = current_dir / "10_backtest.py"
    
    if not os.path.exists(engine_path):
        return "ERR", "ERR", "ERR", "ERR", get_status_ui("crash"), f"Engine Not Found at: {engine_path}", "", go.Figure(), None

    rth_bool = True if rth_value and rth_value[0] is True else False
    archive_bool = True 

    # CONSTRUCT COMMAND WITH MARKET OPEN SAFETY
    cmd = [
        sys.executable, 
        str(engine_path),
        "--start_date", str(start_date), "--end_date", str(end_date),
        "--start_balance", str(start_balance), "--pos_size_pct", str(pos_size / 100.0),
        "--max_invest", str(max_invest), "--tax_rate", str(tax_rate),
        "--trailing_stop_pct", str(trail_pct / 100.0), 
        "--enforce_rth", str(rth_bool), "--archive_report", str(archive_bool),
        "--selection_mode", str(selection_mode),
        "--ideal_gain_pct", str(ideal_gain_val / 100.0),
        "--strike_offset", str(strike_offset_val),
        "--skip_open_minutes", "15" # SAFETY BUFFER
    ]
    
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR)
    keys_to_remove = ["WERKZEUG_RUN_MAIN", "WERKZEUG_SERVER_FD"]
    for key in keys_to_remove: env.pop(key, None)
        
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, env=env, close_fds=True)
        full_output = process.stdout
        
        if "JSON_RESULT:" in full_output:
            log_text, json_text = full_output.split("JSON_RESULT:")
            result = json.loads(json_text)
            
            if "error" in result:
                 return "--", "--", "--", "--", get_status_ui("failure", result['error']), "", log_text, go.Figure(), None 

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=list(range(len(result['equity_curve']))), 
                y=result['equity_curve'], 
                mode='lines', 
                name="Equity", 
                line=dict(color='#00ff41', width=3)
            ))
            fig.add_hline(y=start_balance, line_dash="dot", line_color="#888")
            fig.update_layout(template="plotly_dark", title="Equity Curve", margin=dict(t=10, b=10, l=10, r=10), height=350, yaxis_title="$")

            trade_table = generate_trade_table(
                result['trade_dates'],
                result.get('trade_tickers', []),
                result.get('trade_entries', []),
                result.get('trade_exits', []),
                result.get('trade_reasons', []),
                result['trade_pnl'],
                result['trade_returns']
            )

            return (
                f"${result['final_balance']:,.2f}",
                html.Span(f"{result['total_return_pct']:+.1f}%", className="text-success" if result['total_return_pct'] > 0 else "text-danger"),
                html.Span(f"{result['max_drawdown_pct']:.1f}%", className="text-danger"),
                f"{result['win_rate']:.1f}%",
                get_status_ui("success", "Analysis Complete"), 
                "", 
                log_text, 
                fig, 
                trade_table
            )
        else:
            return "--", "--", "--", "--", get_status_ui("crash"), "Execution Failed", full_output, go.Figure(), None

    except Exception as e:
        return "--", "--", "--", "--", get_status_ui("crash"), f"GUI Error: {str(e)}", "", go.Figure(), None