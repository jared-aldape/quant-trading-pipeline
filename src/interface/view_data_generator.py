import dash
from dash import dcc, html, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
from datetime import date, timedelta
import sys
from pathlib import Path

# PATH CONFIG
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_backtest
from src.utils import config
from src.utils.date_profiles import DATE_PROFILES 

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # --- TITLE ROW ---
        dbc.Row([
            dbc.Col([
                html.H2("BACKTEST SEQUENCE GENERATOR", className="fw-bold text-white mb-0"),
                html.P("QUANTITATIVE BACKTEST ENGINE | SNAPSHOT PROTOCOL ENABLED", className="text-muted small fw-bold mb-0")
            ], width=8),
            
            dbc.Col([
                html.Div("ENGINE STATUS: READY", className="text-end text-success font-monospace fw-bold"),
                html.Div("DB LOCK BYPASS: ACTIVE", className="text-end text-warning font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # --- MAIN CONSOLE ROW ---
        dbc.Row([
            # LEFT: SYSTEM CONFIGURATION
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("SYSTEM CONFIGURATION", className="fw-bold font-monospace"),
                    dbc.CardBody([
                        html.Label("STRATEGY PROFILE", className="small text-muted fw-bold"),
                        # ⚡ SWITCHED TO dbc.Select (Native HTML Dropdown)
                        dbc.Select(
                            id='gen-profile',
                            options=[
                                {'label': 'GIL LEDGER (Robinhood)', 'value': 'LIVE_RH'},
                                {'label': 'MANUAL SIMULATOR', 'value': 'MANUAL_SIM'},
                                {'label': 'OPTIMIZED SIGNALS (ALL)', 'value': 'ALGO_SIGNALS'},
                                {'label': 'CALLS ONLY', 'value': 'ALL_CALL'},
                                {'label': 'PUTS ONLY', 'value': 'ALL_PUT'}
                            ],
                            value='ALGO_SIGNALS',
                            className="mb-3 bg-white text-dark font-monospace"
                        ),

                        html.Label("TIME HORIZON PROFILE", className="small text-muted fw-bold"),
                        dbc.Select(
                            id='gen-date-profile',
                            options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                            value='Last 30 Days',
                            className="mb-3 bg-white text-dark font-monospace"
                        ),

                        dbc.Row([
                            dbc.Col([
                                html.Label("START DATE", className="small text-muted fw-bold"),
                                dcc.DatePickerSingle(id='gen-start-date', date=date.today()-timedelta(days=30), display_format='YYYY-MM-DD', className="d-block mb-2")
                            ], width=6),
                            dbc.Col([
                                html.Label("END DATE", className="small text-muted fw-bold"),
                                dcc.DatePickerSingle(id='gen-end-date', date=date.today(), display_format='YYYY-MM-DD', className="d-block mb-2")
                            ], width=6),
                        ]),

                        html.Label("STARTING CAPITAL ($)", className="small text-muted fw-bold mt-2"),
                        dbc.Input(id='gen-capital', type='number', value=2000, step=100, className="mb-3 font-monospace bg-white text-dark"),

                        html.Label("SELECTION LOGIC", className="small text-muted fw-bold"),
                        dbc.Select(
                            id='gen-selection',
                            options=[
                                {'label': 'FIRST SIGNAL', 'value': 'FIRST'},
                                {'label': 'BEST SIGNAL', 'value': 'BEST'},
                                {'label': 'ALL SIGNALS', 'value': 'ALL'}
                            ],
                            value='FIRST',
                            className="mb-4 bg-white text-dark font-monospace"
                        ),

                        dbc.Button("INITIALIZE BACKTEST", id='gen-btn', color="primary", className="w-100 fw-bold py-2")
                    ])
                ], className="shadow-sm border-secondary h-100")
            ], width=4),

            # MIDDLE: MISSION PARAMETERS
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("MISSION PARAMETERS", className="fw-bold font-monospace"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("IDEAL GAIN %", className="small text-muted fw-bold"),
                                dbc.Input(id='gen-ideal-gain', type='number', value=30, step=5, className="mb-2 font-monospace bg-white text-dark")
                            ], width=6),
                            dbc.Col([
                                html.Label("TRAILING STOP %", className="small text-muted fw-bold"),
                                dbc.Input(id='gen-trail-stop', type='number', value=15, step=5, className="mb-2 font-monospace bg-white text-dark")
                            ], width=6),
                        ], className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                html.Label("MAX LOSS %", className="small text-muted fw-bold"),
                                dbc.Input(id='gen-max-loss', type='number', value=50, step=10, className="mb-2 font-monospace bg-white text-dark")
                            ], width=6),
                        ], className="mb-3"),

                        html.Label("FEE model", className="small text-muted fw-bold"),
                        dbc.Select(
                            id='gen-fee-model',
                            options=[
                                {'label': 'ROBINHOOD GOLD (Low)', 'value': 'RH_GOLD'},
                                {'label': 'STANDARD BROKER (Mid)', 'value': 'STD'},
                                {'label': 'PROP FIRM (High)', 'value': 'PROP'}
                            ],
                            value='RH_GOLD',
                            className="mb-3 bg-white text-dark font-monospace"
                        ),
                        
                        html.Label("TAX RATE", className="small text-muted fw-bold"),
                        dbc.Select(
                            id='gen-tax-rate',
                            options=[
                                {'label': 'SECTION 1256 (26%)', 'value': 26},
                                {'label': 'SHORT TERM (37%)', 'value': 37},
                                {'label': 'NONE (0%)', 'value': 0}
                            ],
                            value=26,
                            className="mb-3 bg-white text-dark font-monospace"
                        ),
                        
                        html.Div("Simulation parameters apply to Algo profiles.", className="text-muted small mt-3 fst-italic text-center")
                    ])
                ], className="shadow-sm border-secondary h-100")
            ], width=4),

            # RIGHT: ANALYTICS REPORT
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ANALYTICS REPORT", className="fw-bold font-monospace text-success"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Div("FINAL BALANCE", className="text-muted small fw-bold"), html.H3(id='gen-bal', children="$0.00", className="text-white font-monospace fw-bold")], width=6),
                            dbc.Col([html.Div("NET RETURN", className="text-muted small fw-bold"), html.H3(id='gen-ret', children="0.0%", className="text-white font-monospace fw-bold")], width=6),
                        ], className="text-center mb-3"),
                        
                        html.Hr(className="border-secondary"),

                        dbc.Row([
                            dbc.Col([html.Div("WIN RATE", className="small text-muted fw-bold"), html.H4(id='gen-wr', children="0%", className="text-info font-monospace")], width=4, className="text-center"),
                            dbc.Col([html.Div("TRADES", className="small text-muted fw-bold"), html.H4(id='gen-count', children="0", className="text-white font-monospace")], width=4, className="text-center"),
                            dbc.Col([html.Div("W/L RATIO", className="small text-muted fw-bold"), html.H4(id='gen-wl', children="0/0", className="text-muted font-monospace")], width=4, className="text-center"),
                        ], className="mb-3"),

                        html.Hr(className="border-secondary"),

                        dbc.Row([
                            dbc.Col([html.Div("GROSS PnL", className="small text-muted fw-bold"), html.Div(id='gen-gross', children="$0.00", className="text-white fw-bold font-monospace")], width=4),
                            dbc.Col([html.Div("FEES & FRICTION", className="small text-muted fw-bold"), html.Div(id='gen-fees', children="$0.00", className="text-danger fw-bold font-monospace")], width=4),
                            dbc.Col([html.Div("NET PnL", className="small text-muted fw-bold"), html.Div(id='gen-net', children="$0.00", className="text-success fw-bold font-monospace")], width=4),
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-secondary h-100")
            ], width=4),
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("EQUITY GROWTH CURVE", className="fw-bold font-monospace small"),
                    dbc.CardBody(dcc.Graph(id='gen-chart', style={'height': '400px'}, config={'displayModeBar': False}))
                ], className="shadow-sm border-secondary")
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                html.H5("STRATEGY EXECUTION LEDGER", className="text-info font-monospace mb-3"),
                html.Div(id='gen-table-container')
            ], width=12)
        ])

    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================
@callback(
    [Output('gen-selection', 'value'), Output('gen-selection', 'disabled')],
    Input('gen-profile', 'value')
)
def toggle_selection_mode(profile):
    if profile in ['LIVE_RH', 'MANUAL_SIM']:
        return 'FIRST', True
    return 'FIRST', False

@callback(
    [Output('gen-start-date', 'date'), Output('gen-end-date', 'date')],
    Input('gen-date-profile', 'value')
)
def update_date_range(profile_name):
    if not profile_name or profile_name not in DATE_PROFILES:
        return no_update, no_update
    profile = DATE_PROFILES[profile_name]
    return profile.start_date, profile.end_date

@callback(
    [Output('gen-bal', 'children'), Output('gen-ret', 'children'),
     Output('gen-wr', 'children'), Output('gen-count', 'children'), Output('gen-wl', 'children'),
     Output('gen-gross', 'children'), Output('gen-fees', 'children'), Output('gen-net', 'children'),
     Output('gen-chart', 'figure'), Output('gen-table-container', 'children')],
    [Input('gen-btn', 'n_clicks')],
    [State('gen-start-date', 'date'), State('gen-end-date', 'date'),
     State('gen-capital', 'value'), State('gen-profile', 'value'), 
     State('gen-selection', 'value'),
     State('gen-ideal-gain', 'value'), State('gen-trail-stop', 'value'),
     State('gen-max-loss', 'value'), State('gen-fee-model', 'value'), State('gen-tax-rate', 'value')]
)
def update_gen_stats(n, start_date, end_date, capital, profile, selection, 
                     ideal_gain, trail_stop, max_loss, fee_model, tax_rate):
    if not n: return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, go.Figure(), ""
    
    mission_params = {
        'ideal_gain': ideal_gain, 'trail_stop': trail_stop,
        'max_loss': max_loss, 'fee_model': fee_model, 'tax_rate': tax_rate
    }

    # ⚡ ENGINE CALL WITH ERROR HANDLING
    try:
        trades, equity, final_bal, ret_pct, report = engine_backtest.run_backtest(
            start_date, end_date, capital, profile, selection, mission_params
        )
    except Exception as e:
        return f"ERR", "!", "!", "!", "!", "!", "!", "!", go.Figure(), html.Div(f"ENGINE CRASHED: {e}", className="text-danger font-monospace")
    
    if not report:
        report = {'net_pnl': 0.0, 'win_rate': 0.0, 'count': 0, 'wins': 0, 'losses': 0, 'gross_pnl': 0.0, 'friction': 0.0}

    df_eq = pd.DataFrame(equity)
    fig = go.Figure()
    if not df_eq.empty:
        fig.add_trace(go.Scatter(x=df_eq['Date'], y=df_eq['Balance'], mode='lines+markers', line=dict(color='#00d2ff', width=3), fill='tozeroy', fillcolor='rgba(0, 210, 255, 0.05)'))
    
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family="monospace"))

    if not trades:
        tbl = html.Div("No strategy execution found.", className="text-center text-muted py-5 font-monospace")
    else:
        rows = [html.Tr([
            html.Td(t['Date'], className="text-muted"), html.Td(t['Ticker'], className="text-white fw-bold"),
            html.Td(t['Type'], className="text-info" if 'CALL' in str(t['Type']).upper() else "text-danger"),
            html.Td(t['Entry_Time'], className="text-muted"), html.Td(t['Exit_Time'], className="text-muted"),
            html.Td(t['Duration'], className="text-white"),
            html.Td(f"{t['Return']:.1f}%", style={'color': "var(--inst-success)" if t.get('PnL', 0) >= 0 else "var(--inst-danger)"}),
            html.Td(f"${t['Balance']:,.2f}", className="text-white"),
            html.Td(f"${t['Tax']:,.2f}", className="text-danger small"),
            html.Td(f"${t['TakeHome']:,.2f}", className="text-success fw-bold")
        ]) for t in trades]
        tbl = dbc.Table([html.Thead(html.Tr([html.Th("DATE"), html.Th("TICKER"), html.Th("TYPE"), html.Th("ENTRY"), html.Th("EXIT"), html.Th("DUR"), html.Th("ROI %"), html.Th("EQUITY"), html.Th("TAX"), html.Th("NET")]))] + [html.Tbody(rows)], className="table font-monospace", style={"backgroundColor": "#0f172a", "fontSize": "12px"})

    return f"${final_bal:,.2f}", f"{ret_pct:+.1f}%", f"{report['win_rate']:.1f}%", f"{report['count']}", f"{report['wins']}/{report['losses']}", f"${report['gross_pnl']:,.2f}", f"${report['friction']:,.2f}", f"${report['net_pnl']:,.2f}", fig, tbl