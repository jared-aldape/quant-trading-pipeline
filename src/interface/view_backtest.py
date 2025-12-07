import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import traceback 
from datetime import date, datetime, timedelta
from src.core import engine_backtest
from src.utils import config

# ==============================================================================
# 1. THE BRIDGE (Argument Container)
# ==============================================================================
class BacktestArgs:
    def __init__(self, start, end, bal, mode, tax, trail, gain, be_trigger, selection, export, slip, comm, fee_model, sma_p, rsi_over, rsi_under):
        self.start_date = start
        self.end_date = end
        try: self.start_balance = float(bal) if bal else 1000.0
        except: self.start_balance = 1000.0
        self.strategy_mode = mode if mode else 'Fractal'
        try: self.tax_rate = float(tax) if tax else 0.0
        except: self.tax_rate = 0.0
        
        # Execution Params (Passed to Engine logic if supported)
        try: self.trailing_stop_pct = (float(trail) / 100.0) if trail else None
        except: self.trailing_stop_pct = None
        try: self.ideal_gain_pct = (float(gain) / 100.0) if gain else None
        except: self.ideal_gain_pct = None
        try: self.breakeven_pct = (float(be_trigger) / 100.0) if be_trigger else None
        except: self.breakeven_pct = None
        
        self.selection_mode = selection if selection else 'FIRST'
        self.archive_report = True if (export and export[0]) else False
        
        # Friction
        try: self.slippage = float(slip) if slip is not None else 0.0
        except: self.slippage = 0.0
        try: self.commission = float(comm) if comm is not None else 0.65
        except: self.commission = 0.65
        self.fee_model = fee_model if fee_model else 'RH_GOLD'
        
        # Filters
        try: self.sma_period = int(sma_p) if sma_p else 20
        except: self.sma_period = 20
        try: self.rsi_over = float(rsi_over) if rsi_over else 70
        except: self.rsi_over = 70
        try: self.rsi_under = float(rsi_under) if rsi_under else 30
        except: self.rsi_under = 30

# ==============================================================================
# 2. HELPER UI COMPONENTS
# ==============================================================================
def get_status_ui(status_type, message=None):
    if status_type == "ready":
        return html.Div([html.Div("📊", className="display-4"), html.H4("Ready for Analysis", className="text-muted")], className="text-center")
    elif status_type == "success":
        return html.Div([html.Div("✅", className="display-4"), html.H4(message, className="text-success")], className="text-center")
    elif status_type == "failure":
        return html.Div([html.Div("⚠️", className="display-4"), html.H4(message, className="text-warning")], className="text-center")
    elif status_type == "crash":
        return html.Div([html.Div("💀", className="display-4"), html.H4("Execution Crash", style={"color": "#a855f7"})], className="text-center")

# ==============================================================================
# 3. RENDER LAYOUT
# ==============================================================================
def render():
    today = date.today()
    default_start = (today - timedelta(days=60)).strftime("%Y-%m-%d")
    
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("DATA GENERATOR", className="display-6 fw-bold text-white"),
                html.P("Historical Strategy Validation Engine", className="text-muted lead")
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            # --- LEFT COLUMN: CONTROLS ---
            dbc.Col([
                # MISSION CARD
                dbc.Card([
                    dbc.CardHeader("MISSION PARAMETERS", className="fw-bold text-warning", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        html.Label("Backtest Period"),
                        dcc.DatePickerRange(
                            id='bt-date-range',
                            start_date=default_start, end_date=today,
                            display_format='YYYY-MM-DD',
                            className="mb-3 w-100",
                            style={'backgroundColor': '#222', 'color': '#fff', 'border': '1px solid #444'}
                        ),
                        dbc.Row([
                            dbc.Col([html.Label("Start Capital ($)"), dbc.Input(id='bt-balance', type='number', value=1000, className="mb-2")], width=6),
                            dbc.Col([html.Label("Tax Rate (Est.)"), dbc.Input(id='bt-tax-rate', type='number', value=0.26, step=0.01, className="mb-2")], width=6)
                        ]),
                        html.Hr(className="my-2"),
                        html.Label("Portfolio Mode"),
                        dcc.Dropdown(
                            id='bt-mode',
                            options=[
                                {'label': 'Fractal (Scanner Truth)', 'value': 'Fractal'},
                                {'label': 'Macro (Dynamic Bias)', 'value': 'Macro'},
                                {'label': 'Hedged (Smart Switch)', 'value': 'Hedged'}, # Mapped to engine
                                {'label': 'Call (Long Only)', 'value': 'Call'},
                                {'label': 'Put (Long Only)', 'value': 'Put'}
                            ],
                            value='Hedged', clearable=False, className="mb-3", style={'color': '#000'}
                        ),
                        html.Label("Signal Selection Strategy"),
                        dcc.Dropdown(
                            id='bt-selection',
                            options=[
                                {'label': '⚡ Standard (First Signal)', 'value': 'FIRST'},
                                {'label': '🔮 Optimized (Best Outcome)', 'value': 'BEST'}
                            ],
                            value='FIRST', clearable=False, className="mb-3", style={'color': '#000'}
                        ),
                        dbc.Checklist(
                            options=[{"label": " Export Report to CSV", "value": True}],
                            value=[], id="bt-export", switch=True, className="mb-3 text-info"
                        ),
                        dbc.Button("▶ RUN SIMULATION", id='btn-run-backtest', color="success", className="w-100 fw-bold")
                    ])
                ], className="shadow mb-3"),
                
                # RISK & FRICTION CARD
                dbc.Card([
                    dbc.CardHeader("RISK & FRICTION (The Vig)", className="fw-bold text-white", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Label("Trailing Stop (%)"), dbc.Input(id='bt-trail-pct', type='number', value=25, className="form-control mb-2")], width=6),
                            dbc.Col([html.Label("Ideal Gain (%)"), dbc.Input(id='bt-ideal-gain', type='number', value=100, className="form-control mb-2")], width=6),
                        ]),
                        dbc.Row([
                            dbc.Col([html.Label("Breakeven Trigger (%)"), dbc.Input(id='bt-be-trigger', type='number', value=15, className="form-control mb-2")], width=12),
                        ]),
                        html.Hr(className="my-2"),
                        html.Label("Fee Structure"),
                        dcc.Dropdown(
                            id='bt-fee-model',
                            options=[
                                {'label': '⛔ None (Zero Fees)', 'value': 'NONE'},
                                {'label': '🛠️ Manual (Fixed Rate)', 'value': 'MANUAL'},
                                {'label': '🏹 Robinhood (Gold)', 'value': 'RH_GOLD'},
                                {'label': '🏹 Robinhood (Standard)', 'value': 'RH_STD'}
                            ],
                            value='RH_GOLD', clearable=False, className="mb-3", style={'color': '#000'}
                        ),
                        dbc.Row([
                            dbc.Col([html.Label("Slippage ($/Share)"), dbc.Input(id='bt-slippage', type='number', value=0.01, step=0.01, className="form-control")], width=6),
                            dbc.Col([html.Label("Manual Comm ($)"), dbc.Input(id='bt-commission', type='number', value=0.65, step=0.01, disabled=True, className="form-control")], width=6),
                        ]),
                    ])
                ], className="shadow mb-3"),

                # GATEKEEPER CARD
                dbc.Card([
                    dbc.CardHeader("GATEKEEPER (Entry Filters)", className="fw-bold text-success", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        html.Label("Trend (SMA)"),
                        dbc.Row([
                            dbc.Col([html.Label("SMA Period"), dbc.Input(id='bt-filter-sma', type='number', value=20, className="form-control")], width=6),
                            dbc.Col([html.Label("Filter Enabled"), dbc.Checklist(options=[{"label": "ON", "value": True}], value=[], id="bt-filter-sma-on", switch=True, className="mt-2 text-success")], width=6),
                        ]),
                        html.Hr(className="my-2"),
                        html.Label("Momentum (RSI)"),
                        dbc.Row([
                            dbc.Col([html.Label("RSI Period"), dbc.Input(id='bt-filter-rsi-p', type='number', value=14, className="form-control")], width=4),
                            dbc.Col([html.Label("RSI Over"), dbc.Input(id='bt-filter-rsi-over', type='number', value=70, className="form-control")], width=4),
                            dbc.Col([html.Label("RSI Under"), dbc.Input(id='bt-filter-rsi-under', type='number', value=30, className="form-control")], width=4),
                        ]),
                    ])
                ], className="shadow mb-3"),
                
            ], width=12, md=4),

            # --- RIGHT COLUMN: VISUALIZATION ---
            dbc.Col([
                # EQUITY CURVE
                dbc.Card([
                    dbc.CardHeader("EQUITY CURVE", className="fw-bold text-primary", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        dcc.Loading(dcc.Graph(id='bt-equity-chart', style={'height': '350px'}, config={'displayModeBar': False})),
                        html.Div(id='bt-status-area', children=get_status_ui("ready"), className="mb-4 mt-3"),
                    ], style={'padding': '10px'})
                ], className="mb-3 shadow"),

                # REPORT SUMMARY GRID
                dbc.Card([
                    dbc.CardHeader("REPORT SUMMARY", className="fw-bold text-success", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.H6("Final Balance", className="text-muted"), html.H3(id='bt-res-balance', children="--")], className="text-center"),
                            dbc.Col([html.H6("Net Return (Post-Tax)", className="text-muted"), html.H3(id='bt-res-return', children="--")], className="text-center"),
                            dbc.Col([html.H6("Signal Freq %", className="text-muted"), html.H3(id='bt-res-sig-avg', children="--")], className="text-center"),
                        ], className="text-center mb-3"),
                        dbc.Row([
                            dbc.Col([html.H6("Max Drawdown", className="text-muted"), html.H4(id='bt-res-dd', children="--")], className="text-center"),
                            dbc.Col([html.H6("Avg Duration", className="text-muted"), html.H4(id='bt-res-duration', children="--")], className="text-center"),
                            dbc.Col([html.H6("Dominance", className="text-muted"), html.H4(id='bt-res-bias', children="--")], className="text-center"),
                        ]),
                    ])
                ], className="mb-3 shadow"),
                
                # TRADE LEDGER
                dbc.Card([
                    dbc.CardHeader("LEDGER LOGS (Detailed Trades)", className="fw-bold text-white", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        html.Div(id='bt-trade-table', style={'overflowY': 'scroll', 'height': '500px'})
                    ], className="p-0")
                ], className="mb-4 shadow")

            ], width=12, lg=8)
        ])
    ], fluid=True)

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    Output('bt-commission', 'disabled'),
    Input('bt-fee-model', 'value')
)
def toggle_commission_input(fee_model):
    if fee_model == 'MANUAL': return False
    return True

@callback(
    [Output('bt-res-balance', 'children'), Output('bt-res-return', 'children'),
     Output('bt-res-sig-avg', 'children'), Output('bt-res-dd', 'children'),
     Output('bt-res-duration', 'children'), Output('bt-res-bias', 'children'),
     Output('bt-equity-chart', 'figure'), Output('bt-trade-table', 'children'),
     Output('bt-status-area', 'children')],
    [Input('btn-run-backtest', 'n_clicks')],
    [State('bt-date-range', 'start_date'), State('bt-date-range', 'end_date'),
     State('bt-balance', 'value'), State('bt-mode', 'value'),
     State('bt-tax-rate', 'value'), State('bt-trail-pct', 'value'),
     State('bt-ideal-gain', 'value'), State('bt-be-trigger', 'value'),
     State('bt-selection', 'value'), State('bt-export', 'value'),
     State('bt-slippage', 'value'), State('bt-commission', 'value'),
     State('bt-fee-model', 'value'), 
     State('bt-filter-sma', 'value'), State('bt-filter-rsi-p', 'value'),
     State('bt-filter-rsi-over', 'value'), State('bt-filter-rsi-under', 'value'),
     State('bt-filter-sma-on', 'value')]
)
def update_backtest(n, start, end, balance, mode, tax, trail, gain, be_trigger, selection, export, slip, comm, fee_model, sma_p, rsi_p, rsi_over, rsi_under, sma_on):
    if not n: return dash.no_update
    
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    try:
        # 1. Build Args
        args = BacktestArgs(start, end, balance, mode, tax, trail, gain, be_trigger, selection, export, slip, comm, fee_model, sma_p, rsi_over, rsi_under)
        args.sma_filter_on = True if sma_on and sma_on[0] else False
        args.rsi_period = rsi_p
        
        # 2. Bridge to v3.3 Engine
        try:
            d_start = datetime.strptime(start, '%Y-%m-%d')
            d_end = datetime.strptime(end, '%Y-%m-%d')
            days_delta = (d_end - d_start).days
            if days_delta < 1: days_delta = 1
        except: days_delta = 30

        hedged_mode = True
        if mode in ['Call', 'Put']: hedged_mode = False 
        if mode == 'Hedged': hedged_mode = True
        
        # EXECUTE SIMULATION
        results = engine_backtest.run_backtest_session(
            initial_balance=args.start_balance,
            days=days_delta,
            selection_mode=args.selection_mode,
            hedged_mode=hedged_mode
        )
        
        if results is None or results.empty:
            return "--", "--", "--", "--", "--", "--", empty_fig, [], get_status_ui("failure", "No trades found.")
            
        # 3. Post-Process Metrics
        def clean_money(s): return float(str(s).replace('$','').replace(',',''))
        results['clean_bal'] = results['Balance'].apply(clean_money)
        
        # --- DURATION CALCULATION ---
        try:
            # We construct datetime objects for accurate timedelta calc
            results['dt_entry'] = pd.to_datetime(results['Date'].astype(str) + ' ' + results['Time'])
            results['dt_exit'] = pd.to_datetime(results['Date'].astype(str) + ' ' + results['Exit_Time']) # Expects 'Exit_Time' from engine
            
            # Fallback if engine hasn't been updated to return 'Exit_Time' explicitly
            if 'Exit_Time' not in results.columns:
                 # Logic assumes 60m hold if not specified
                 duration_mins = 60
                 avg_duration_str = "60m"
            else:
                results['duration'] = (results['dt_exit'] - results['dt_entry']).dt.total_seconds() / 60
                avg_mins = results['duration'].mean()
                avg_duration_str = f"{int(avg_mins)}m"
        except:
            # Safe Fallback
            avg_duration_str = "60m" 

        # Stats
        final_balance = results.iloc[-1]['clean_bal']
        gross_profit = final_balance - args.start_balance
        net_profit = gross_profit * (1 - args.tax_rate) if gross_profit > 0 else gross_profit
        net_return_pct = (net_profit / args.start_balance) * 100
        
        cum_max = results['clean_bal'].cummax()
        drawdown = (results['clean_bal'] - cum_max) / cum_max
        max_dd = drawdown.min() * 100 if not drawdown.empty else 0.0
        
        # Dominance
        call_count = len(results[results['Type'] == 'CALL'])
        put_count = len(results[results['Type'] == 'PUT'])
        total_trades = len(results)
        
        if total_trades > 0:
            call_pct = int((call_count/total_trades)*100)
            put_pct = int((put_count/total_trades)*100)
            if call_count > put_count: bias_disp = f"CALLS ({call_pct}%)"
            elif put_count > call_count: bias_disp = f"PUTS ({put_pct}%)"
            else: bias_disp = "BALANCED"
        else: bias_disp = "--"

        # 4. Generate Visuals
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=results['Date'], y=results['clean_bal'], mode='lines', line=dict(color='#00bc8c', width=2), fill='tozeroy'))
        fig.add_hline(y=args.start_balance, line_dash="dot", line_color="#666")
        fig.update_layout(template="plotly_dark", margin=dict(l=40, r=40, t=20, b=40), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

        # Trade Table
        table_rows = []
        for i, row in results.iterrows():
            pnl_val = clean_money(row['PnL'])
            is_win = pnl_val >= 0
            style_color = '#00ff41' if is_win else '#ff5555'
            row_bg = 'rgba(0, 255, 65, 0.05)' if is_win else 'rgba(255, 0, 0, 0.05)'
            
            # Calculate duration for row if possible
            duration_disp = "60m" # Default fallback
            
            table_rows.append(html.Tr([
                html.Td(row['Date'], className="small text-muted"), 
                html.Td(row['Time'], className="small"),
                html.Td(row.get('Exit_Time', '60m Later'), className="small"), # Exit Time Column
                html.Td(row['Type'], className="small", style={'color': '#00d2ff' if row['Type']=='CALL' else '#ff5555'}), 
                html.Td(duration_disp, className="small text-muted"), # Duration Column
                html.Td(row['Entry'], className="small text-white-50"),
                html.Td(row['Exit'], className="small text-white-50"),
                html.Td(row['PnL'], style={'color': style_color, 'fontWeight': 'bold'}),
                html.Td(row['Return'], style={'color': style_color}) 
            ], style={'backgroundColor': row_bg}))
            
        tbl = dbc.Table(
            [html.Thead(html.Tr([
                html.Th("Date"), html.Th("Entry"), html.Th("Exit"), html.Th("Type"), 
                html.Th("Dur"), html.Th("Entry $"), html.Th("Exit $"), html.Th("PnL"), html.Th("ROI")
            ]))] + 
            [html.Tbody(table_rows)], 
            bordered=False, hover=True, color="dark", size="sm"
        )

        return f"${final_balance:,.2f}", html.Span(f"{net_return_pct:+.1f}%", className="text-success" if net_return_pct > 0 else "text-danger"), f"{total_trades} Trades", html.Span(f"{max_dd:.1f}%", className="text-danger"), avg_duration_str, html.Span(bias_disp, className="text-info"), fig, tbl, get_status_ui("success", f"Sim Complete: {total_trades} Trades")
        
    except Exception as e:
        traceback.print_exc()
        return "--", "--", "--", "--", "--", "--", empty_fig, [], get_status_ui("crash", str(e))