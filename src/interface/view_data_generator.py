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
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("SAVE CRYSTAL COMMAND", className="magitek-h2"),
                html.P("STRATEGY CONSOLE | BACKTEST ENGINE | RISK SIMULATOR", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: CONFIGURATION", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # --- MAIN CONSOLE ROW ---
        dbc.Row([
            # LEFT FLANK: CONFIGURATION
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("SYSTEM CONFIGURATION", className="card-header"),
                    dbc.CardBody([
                        # 1. STRATEGY
                        html.Label("STRATEGY PROFILE", className="small text-muted font-monospace"),
                        dcc.Dropdown(
                            id='gen-profile',
                            options=[
                                {'label': 'GIL LEDGER (Robinhood)', 'value': 'LIVE_RH'},
                                {'label': 'TRAINING GROUNDS', 'value': 'MANUAL_SIM'},
                                {'label': 'OPTIMIZED SIGNALS (ALL)', 'value': 'ALGO_SIGNALS'},
                                {'label': 'CALLS ONLY', 'value': 'ALL_CALL'},
                                {'label': 'PUTS ONLY', 'value': 'ALL_PUT'}
                            ],
                            value='ALGO_SIGNALS',
                            clearable=False,
                            className="mb-3"
                        ),

                        # 2. TIME HORIZON
                        html.Label("TIME HORIZON", className="small text-muted font-monospace"),
                        dcc.Dropdown(
                            id='gen-date-profile',
                            options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                            value='Last 30 Days',
                            clearable=False,
                            className="mb-3"
                        ),

                        # 3. DATE PICKERS
                        dbc.Row([
                            dbc.Col([
                                html.Label("START DATE", className="small text-muted font-monospace"),
                                dcc.DatePickerSingle(id='gen-start-date', date=date.today()-timedelta(days=30), display_format='YYYY-MM-DD', className="d-block mb-2")
                            ], width=6),
                            dbc.Col([
                                html.Label("END DATE", className="small text-muted font-monospace"),
                                dcc.DatePickerSingle(id='gen-end-date', date=date.today(), display_format='YYYY-MM-DD', className="d-block mb-2")
                            ], width=6),
                        ]),

                        # 4. CAPITAL
                        html.Label("START CAPITAL ($)", className="small text-muted font-monospace mt-2"),
                        dbc.Input(id='gen-capital', type='number', value=2000, step=100, className="mb-3"),

                        # 5. SELECTION
                        html.Label("SELECTION LOGIC", className="small text-muted font-monospace"),
                        dcc.Dropdown(
                            id='gen-selection',
                            options=[
                                {'label': 'FIRST SIGNAL', 'value': 'FIRST'},
                                {'label': 'BEST SIGNAL', 'value': 'BEST'},
                                {'label': 'ALL SIGNALS', 'value': 'ALL'},
                                {'label': 'REALITY (Fixed)', 'value': 'REALITY', 'disabled': True}
                            ],
                            value='FIRST',
                            clearable=False,
                            className="mb-4"
                        ),

                        dbc.Button("INITIALIZE SEQUENCE", id='gen-btn', color="primary", className="w-100 fw-bold")
                    ])
                ], className="shadow h-100")
            ], width=4),

            # MIDDLE FLANK: MISSION PARAMETERS
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("MISSION PARAMETERS", className="card-header"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("IDEAL GAIN %", className="small text-muted font-monospace"),
                                dbc.Input(id='gen-ideal-gain', type='number', value=30, step=5, className="mb-2")
                            ], width=6),
                            dbc.Col([
                                html.Label("TRAILING STOP %", className="small text-muted font-monospace"),
                                dbc.Input(id='gen-trail-stop', type='number', value=15, step=5, className="mb-2")
                            ], width=6),
                        ], className="mb-3"),

                        dbc.Row([
                            dbc.Col([
                                html.Label("MAX LOSS %", className="small text-muted font-monospace"),
                                dbc.Input(id='gen-max-loss', type='number', value=50, step=10, className="mb-2")
                            ], width=6),
                            dbc.Col([], width=6),
                        ], className="mb-3"),

                        html.Label("FEE STRUCTURE", className="small text-muted font-monospace"),
                        dcc.Dropdown(
                            id='gen-fee-model',
                            options=[
                                {'label': 'ROBINHOOD GOLD (Low)', 'value': 'RH_GOLD'},
                                {'label': 'STANDARD BROKER (Mid)', 'value': 'STD'},
                                {'label': 'PROP FIRM (High)', 'value': 'PROP'}
                            ],
                            value='RH_GOLD',
                            clearable=False,
                            className="mb-3"
                        ),
                        
                        html.Label("TAX RATE", className="small text-muted font-monospace"),
                        dcc.Dropdown(
                            id='gen-tax-rate',
                            options=[
                                {'label': 'SECTION 1256 (26%)', 'value': 26},
                                {'label': 'SHORT TERM (37%)', 'value': 37},
                                {'label': 'LONG TERM (15%)', 'value': 15},
                                {'label': 'NONE (0%)', 'value': 0}
                            ],
                            value=26,
                            clearable=False,
                            className="mb-3"
                        ),
                        
                        html.Div("NOTE: Params apply to Sim/Algo. Reality uses actual fills.", className="text-muted small mt-3 fst-italic text-center font-monospace")
                    ])
                ], className="shadow h-100")
            ], width=4),

            # RIGHT FLANK: MISSION REPORT
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("MISSION REPORT & RISK", className="card-header text-success"),
                    dbc.CardBody([
                        # PRIMARY STATS
                        dbc.Row([
                            dbc.Col([html.H6("FINAL BALANCE", className="text-muted small font-monospace"), html.H2(id='gen-bal', children="$0.00", className="text-white font-monospace")], width=6),
                            dbc.Col([html.H6("NET RETURN", className="text-muted small font-monospace"), html.H2(id='gen-ret', children="0.0%", className="text-white font-monospace")], width=6),
                        ], className="text-center mb-3"),
                        
                        html.Hr(className="border-secondary"),

                        dbc.Row([
                            dbc.Col([html.Div("WIN RATE", className="font-monospace"), html.H4(id='gen-wr', children="0%", className="text-info font-monospace")], width=4, className="text-center"),
                            dbc.Col([html.Div("TRADES", className="font-monospace"), html.H4(id='gen-count', children="0", className="text-white font-monospace")], width=4, className="text-center"),
                            dbc.Col([html.Div("W/L RATIO", className="font-monospace"), html.H4(id='gen-wl', children="0/0", className="text-muted font-monospace")], width=4, className="text-center"),
                        ], className="mb-3"),

                        html.Hr(className="border-secondary"),

                        dbc.Row([
                            dbc.Col([html.Div("GROSS PnL", className="small text-muted font-monospace"), html.Div(id='gen-gross', children="$0.00", className="text-white fw-bold font-monospace")], width=4),
                            dbc.Col([html.Div("FEES/VIG", className="small text-muted font-monospace"), html.Div(id='gen-fees', children="$0.00", className="text-danger fw-bold font-monospace")], width=4),
                            dbc.Col([html.Div("NET PnL", className="small text-muted font-monospace"), html.Div(id='gen-net', children="$0.00", className="text-success fw-bold font-monospace")], width=4),
                        ], className="text-center")

                    ])
                ], className="shadow h-100")
            ], width=4),
        ], className="mb-4"),

        # --- VISUALIZATION ROW ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody(dcc.Graph(id='gen-chart', style={'height': '400px'}, config={'displayModeBar': False}))
                ], className="shadow")
            ], width=12)
        ], className="mb-4"),

        # --- DATA LOG ROW ---
        dbc.Row([
            dbc.Col([
                html.H4("EXECUTION LEDGER", className="text-info font-monospace"),
                html.Div(id='gen-table-container')
            ], width=12)
        ])

    ], fluid=True)

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================
@callback(
    [Output('gen-selection', 'value'), Output('gen-selection', 'disabled')],
    Input('gen-profile', 'value')
)
def toggle_selection_mode(profile):
    if profile in ['LIVE_RH', 'MANUAL_SIM']:
        return 'REALITY', True
    return 'FIRST', False

@callback(
    [Output('gen-start-date', 'date'),
     Output('gen-end-date', 'date')],
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
        'ideal_gain': ideal_gain,
        'trail_stop': trail_stop,
        'max_loss': max_loss,
        'fee_model': fee_model,
        'tax_rate': tax_rate
    }

    trades, equity, final_bal, ret_pct, report = engine_backtest.run_backtest(
        start_date, end_date, capital, profile, selection, mission_params
    )
    
    # SAFETY DEFAULTS
    if not report:
        report = {
            'net_pnl': 0.0, 'win_rate': 0.0, 'count': 0, 
            'wins': 0, 'losses': 0, 'gross_pnl': 0.0, 'friction': 0.0
        }
    else:
        report.setdefault('net_pnl', 0.0)
        report.setdefault('win_rate', 0.0)
        report.setdefault('count', 0)
        report.setdefault('wins', 0)
        report.setdefault('losses', 0)
        report.setdefault('gross_pnl', 0.0)
        report.setdefault('friction', 0.0)

    # 1. CHART
    df_eq = pd.DataFrame(equity)
    fig = go.Figure()
    if not df_eq.empty:
        fig.add_trace(go.Scatter(
            x=df_eq['Date'], y=df_eq['Balance'],
            mode='lines+markers',
            line=dict(color='#00d2ff', width=3),
            marker=dict(size=6, color='white', line=dict(width=1, color='#00d2ff')),
            fill='tozeroy', fillcolor='rgba(0, 210, 255, 0.1)'
        ))
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=20, t=20, b=40),
        xaxis=dict(showgrid=False, gridcolor='#444'),
        yaxis=dict(gridcolor='#444', tickprefix="$"),
        font=dict(family="'VT323', monospace", color="white")
    )

    # 2. TABLE (DARK BACKGROUND FORCE)
    if not trades:
        tbl = html.Div("No Trades Found.", className="text-center text-muted mt-5")
    else:
        rows = []
        for t in trades:
            pnl_val = t['PnL'] if isinstance(t['PnL'], (int, float)) else float(str(t['PnL']).replace('$','').replace(',',''))
            row_color = "text-success" if pnl_val >= 0 else "text-danger"
            
            rows.append(html.Tr([
                html.Td(t['Date'], className="text-muted"),
                html.Td(t['Ticker'], className="text-white fw-bold"),
                html.Td(t['Type'], className="text-info" if 'CALL' in str(t['Type']).upper() else "text-danger"),
                html.Td(t['Entry_Time'], className="text-muted"),
                html.Td(t['Exit_Time'], className="text-muted"),
                html.Td(t['Duration'], className="text-white"),
                html.Td(f"{t['Return']:.1f}%", className=f"fw-bold {row_color}"),
                html.Td(f"${t['Balance']:,.2f}", className="text-white"),
                html.Td(f"${t['Tax']:,.2f}", className="text-danger"),
                html.Td(f"${t['TakeHome']:,.2f}", className="text-success fw-bold")
            ]))
            
        header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9'}
        
        tbl = dbc.Table([
            html.Thead(html.Tr([
                html.Th("DATE"), html.Th("TICKER"), html.Th("TYPE"), 
                html.Th("ENTRY TIME"), html.Th("EXIT TIME"), html.Th("DURATION"), 
                html.Th("P/L GAIN (%)"), html.Th("BALANCE"),
                html.Th("TAX"), html.Th("TAKE HOME")
            ], style=header_style))
        ] + [html.Tbody(rows)], 
        hover=True, borderless=True, size='sm',
        className="table",
        style={
            "--bs-table-bg": "#101830",
            "--bs-table-color": "#f3f5f9",
            "--bs-table-hover-bg": "#1c2855",
            "backgroundColor": "#101830",
            "color": "#f3f5f9"
        })

    # 3. STATS
    ret_style = {'color': '#00ff41'} if ret_pct >= 0 else {'color': '#ff5555'}
    net_style = {'color': '#00ff41'} if report['net_pnl'] >= 0 else {'color': '#ff5555'}
    
    return (
        f"${final_bal:,.2f}", 
        html.Span(f"{ret_pct:+.1f}%", style=ret_style),
        f"{report['win_rate']:.1f}%",
        f"{report['count']}",
        f"{report['wins']}/{report['losses']}",
        f"${report['gross_pnl']:,.2f}",
        f"${report['friction']:,.2f}",
        html.Span(f"${report['net_pnl']:,.2f}", style=net_style),
        fig, tbl
    )