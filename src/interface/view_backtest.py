import dash
from dash import dcc, html, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import traceback 
import duckdb
from datetime import date, datetime, timedelta
from src.core import engine_backtest
from src.utils import config
from src.utils.date_profiles import DATE_PROFILES 

# ==============================================================================
# 0. MAGITEK THEME ENGINE (High Contrast / FF6 Style)
# ==============================================================================
THEME = {
    'BG_PAGE': '#000000',           # Keep void background for contrast
    'BG_CARD': '#283878',           # FF6 Classic Blue Window
    'BG_INPUT': '#101830',          # Deep Navy Input Fields
    'BORDER': '2px solid #b5b8b9',  # Steel Window Frame
    'TEXT_MAIN': '#ffffff',         # Pure White
    'TEXT_GOLD': '#fde722',         # Cursor Gold (Headers)
    'TEXT_ACCENT': '#00d2ff',       # Cyan (Secondary Data)
    'SUCCESS': '#00ff41',           # Matrix Green
    'DANGER': '#ff5555',            # Critical Red
    'FONT': 'VT323, monospace'      # Retro Font
}

# Standard Component Styles
STYLE_CARD = {
    'backgroundColor': THEME['BG_CARD'],
    'border': THEME['BORDER'],
    'borderRadius': '6px',
    'boxShadow': '0px 0px 15px rgba(0, 100, 255, 0.3)', # Subtle Blue Glow
    'marginBottom': '20px'
}

STYLE_HEADER = {
    'backgroundColor': 'rgba(0, 0, 0, 0.3)', # Slightly darker shade of the blue
    'borderBottom': '1px solid #fff',
    'color': THEME['TEXT_GOLD'],
    'fontWeight': 'bold',
    'fontFamily': THEME['FONT'],
    'fontSize': '1.2rem',
    'letterSpacing': '1px'
}

STYLE_LABEL = {
    'color': THEME['TEXT_ACCENT'],
    'fontWeight': 'bold',
    'fontSize': '0.9rem',
    'marginBottom': '5px',
    'textTransform': 'uppercase'
}

STYLE_INPUT = {
    'backgroundColor': THEME['BG_INPUT'],
    'border': '1px solid #555',
    'color': '#fff',
    'fontFamily': 'monospace'
}

# ==============================================================================
# 1. THE BRIDGE
# ==============================================================================
class BacktestArgs:
    def __init__(self, start, end, bal, mode, tax, trail, gain, be_trigger, selection, slip, comm, fee_model, sma_p, rsi_over, rsi_under):
        self.start_date = start
        self.end_date = end
        try: self.start_balance = float(bal) if bal else 1000.0
        except: self.start_balance = 1000.0
        self.strategy_mode = mode if mode else 'Fractal'
        try: self.tax_rate = float(tax) if tax else 0.0
        except: self.tax_rate = 0.0
        try: self.trailing_stop_pct = (float(trail) / 100.0) if trail else None
        except: self.trailing_stop_pct = None
        try: self.ideal_gain_pct = (float(gain) / 100.0) if gain else None
        except: self.ideal_gain_pct = None
        try: self.breakeven_pct = (float(be_trigger) / 100.0) if be_trigger else None
        except: self.breakeven_pct = None
        self.selection_mode = selection if selection else 'FIRST'
        try: self.slippage = float(slip) if slip is not None else 0.0
        except: self.slippage = 0.0
        try: self.commission = float(comm) if comm is not None else 0.65
        except: self.commission = 0.65
        self.fee_model = fee_model if fee_model else 'RH_GOLD'
        try: self.sma_period = int(sma_p) if sma_p else 20
        except: self.sma_period = 20
        try: self.rsi_over = float(rsi_over) if rsi_over else 70
        except: self.rsi_over = 70
        try: self.rsi_under = float(rsi_under) if rsi_under else 30
        except: self.rsi_under = 30

def get_status_ui(status_type, message=None):
    if status_type == "ready":
        return html.Div([html.Div("📊", className="display-4", style={'color': THEME['TEXT_ACCENT']}), html.H4("SYSTEM READY", style={'color': '#fff'})], className="text-center")
    elif status_type == "success":
        return html.Div([html.Div("✅", className="display-4"), html.H4(message, style={'color': THEME['SUCCESS']})], className="text-center")
    elif status_type == "failure":
        return html.Div([html.Div("⚠️", className="display-4"), html.H4(message, style={'color': THEME['TEXT_GOLD']})], className="text-center")
    elif status_type == "crash":
        return html.Div([html.Div("💀", className="display-4"), html.H4("CRITICAL ERROR", style={"color": "#a855f7"})], className="text-center")

def save_simulation_to_vault(results_df):
    if results_df is None or results_df.empty: return
    try:
        results_df['entry_time'] = pd.to_datetime(results_df['Date'].astype(str) + ' ' + results_df['Time'].astype(str))
        if 'Exit_Time' in results_df.columns:
            results_df['exit_time_dt'] = pd.to_datetime(results_df['Date'].astype(str) + ' ' + results_df['Exit_Time'].astype(str))
            results_df['duration'] = (results_df['exit_time_dt'] - results_df['entry_time']).dt.total_seconds() / 60
        else:
            results_df['exit_time_dt'] = results_df['entry_time'] + timedelta(minutes=60)
            results_df['duration'] = 60.0
        def clean(x): return float(str(x).replace('$','').replace(',',''))
        export_df = pd.DataFrame()
        export_df['entry_time'] = results_df['entry_time']
        export_df['exit_time'] = results_df['exit_time_dt']
        export_df['ticker'] = results_df['Ticker']
        export_df['net_pnl'] = results_df['PnL'].apply(clean)
        export_df['return_pct'] = results_df['Return'].apply(lambda x: float(str(x).replace('%','')))
        export_df['reason'] = results_df['Type']
        export_df['entry_price'] = results_df['Entry'].apply(clean)
        export_df['exit_price'] = results_df['Exit'].apply(clean)
        export_df['duration_mins'] = results_df['duration']
        con = duckdb.connect(str(config.DB_FILE))
        con.execute(f"DELETE FROM {config.TBL_SIM_LOG}") 
        con.execute(f"INSERT INTO {config.TBL_SIM_LOG} SELECT * FROM export_df")
        con.close()
    except Exception as e:
        print(f"Failed to save sim: {e}")

# ==============================================================================
# 3. RENDER LAYOUT
# ==============================================================================
def render():
    today = date.today()
    default_start = (today - timedelta(days=60)).strftime("%Y-%m-%d")
    
    return dbc.Container([
        # --- TITLE BLOCK ---
        dbc.Row([
            dbc.Col([
                html.H1("DATA GENERATOR", className="display-4", style={'color': THEME['TEXT_MAIN'], 'textShadow': f"0 0 10px {THEME['TEXT_ACCENT']}", 'fontFamily': THEME['FONT']}),
                html.P("HISTORICAL STRATEGY VALIDATION ENGINE", style={'color': THEME['TEXT_GOLD'], 'letterSpacing': '2px'})
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            # --- LEFT COLUMN: CONTROLS ---
            dbc.Col([
                # MISSION CARD
                dbc.Card([
                    dbc.CardHeader("MISSION CONFIGURATION", style=STYLE_HEADER),
                    dbc.CardBody([
                        # Date Logic
                        html.Label("TIME PROFILE", style=STYLE_LABEL),
                        dcc.Dropdown(
                            id='bt-date-profile',
                            options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                            placeholder="SELECT PROFILE...",
                            className="mb-2",
                            style={'backgroundColor': '#fff', 'color': '#000'} # Dropdowns need white bg for readability
                        ),
                        html.Label("CUSTOM RANGE", style=STYLE_LABEL),
                        dcc.DatePickerRange(
                            id='bt-date-range',
                            start_date=default_start, end_date=today,
                            display_format='YYYY-MM-DD',
                            className="mb-3 w-100",
                            style={'backgroundColor': THEME['BG_INPUT'], 'border': '1px solid #555'}
                        ),
                        dbc.Row([
                            dbc.Col([html.Label("START CAPITAL ($)", style=STYLE_LABEL), dbc.Input(id='bt-balance', type='number', value=1000, style=STYLE_INPUT, className="mb-2")], width=6),
                            dbc.Col([html.Label("TAX RATE (%)", style=STYLE_LABEL), dbc.Input(id='bt-tax-rate', type='number', value=0.26, step=0.01, style=STYLE_INPUT, className="mb-2")], width=6)
                        ]),
                        html.Hr(style={'borderColor': '#fff', 'opacity': '0.3'}),
                        
                        html.Label("STRATEGY MODE", style=STYLE_LABEL),
                        dcc.Dropdown(
                            id='bt-mode',
                            options=[
                                {'label': 'Fractal (Pure Signal)', 'value': 'Fractal'},
                                {'label': 'Hedged (Standard)', 'value': 'Hedged'},
                                {'label': 'Call Dominance (75/25)', 'value': 'Call 75/25'},
                                {'label': 'Put Dominance (75/25)', 'value': 'Put 75/25'},
                                {'label': 'Call Only (Long)', 'value': 'Call'},
                                {'label': 'Put Only (Short)', 'value': 'Put'}
                            ],
                            value='Fractal', clearable=False, className="mb-3", style={'color': '#000'}
                        ),
                        html.Label("SELECTION LOGIC", style=STYLE_LABEL),
                        dcc.Dropdown(
                            id='bt-selection',
                            options=[
                                {'label': '⚡ Standard (First Signal)', 'value': 'FIRST'},
                                {'label': '🔮 Optimized (Best Outcome)', 'value': 'BEST'}
                            ],
                            value='FIRST', clearable=False, className="mb-3", style={'color': '#000'}
                        ),
                        dbc.Button("▶ INITIATE SIMULATION", id='btn-run-backtest', color="success", className="w-100 fw-bold mt-3", style={'border': '1px solid #fff', 'boxShadow': '0 0 10px #00ff41'})
                    ])
                ], style=STYLE_CARD),
                
                # RISK CARD
                dbc.Card([
                    dbc.CardHeader("RISK & FRICTION", style=STYLE_HEADER),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Label("TRAILING STOP (%)", style=STYLE_LABEL), dbc.Input(id='bt-trail-pct', type='number', value=25, style=STYLE_INPUT, className="mb-2")], width=6),
                            dbc.Col([html.Label("IDEAL GAIN (%)", style=STYLE_LABEL), dbc.Input(id='bt-ideal-gain', type='number', value=100, style=STYLE_INPUT, className="mb-2")], width=6)
                        ]),
                        html.Label("BREAKEVEN TRIGGER (%)", style=STYLE_LABEL),
                        dbc.Input(id='bt-be-trigger', type='number', value=15, style=STYLE_INPUT, className="mb-3"),
                        
                        html.Hr(style={'borderColor': '#fff', 'opacity': '0.3'}),
                        html.Label("FEE STRUCTURE", style=STYLE_LABEL),
                        dcc.Dropdown(
                            id='bt-fee-model',
                            options=[
                                {'label': 'RH Gold', 'value': 'RH_GOLD'},
                                {'label': 'None', 'value': 'NONE'},
                                {'label': 'Manual', 'value': 'MANUAL'}
                            ],
                            value='RH_GOLD', clearable=False, className="mb-3", style={'color': '#000'}
                        ),
                        dbc.Row([
                            dbc.Col([html.Label("SLIPPAGE ($)", style=STYLE_LABEL), dbc.Input(id='bt-slippage', type='number', value=0.01, step=0.01, style=STYLE_INPUT)], width=6),
                            dbc.Col([html.Label("COMM ($)", style=STYLE_LABEL), dbc.Input(id='bt-commission', type='number', value=0.65, disabled=True, style=STYLE_INPUT)], width=6),
                        ]),
                    ])
                ], style=STYLE_CARD),

                # GATEKEEPER CARD
                dbc.Card([
                    dbc.CardHeader("GATEKEEPER FILTERS", style=STYLE_HEADER),
                    dbc.CardBody([
                        html.Label("TREND (SMA)", style=STYLE_LABEL),
                        dbc.Row([
                            dbc.Col([dbc.Input(id='bt-filter-sma', type='number', value=20, style=STYLE_INPUT)], width=6),
                            dbc.Col([dbc.Checklist(options=[{"label": "ACTIVE", "value": True}], value=[], id="bt-filter-sma-on", switch=True, className="mt-2", style={'color': THEME['SUCCESS']})], width=6),
                        ]),
                        html.Hr(style={'borderColor': '#fff', 'opacity': '0.3'}),
                        html.Label("MOMENTUM (RSI)", style=STYLE_LABEL),
                        dbc.Row([
                            dbc.Col([dbc.Input(id='bt-filter-rsi-p', value=14, style=STYLE_INPUT)], width=4),
                            dbc.Col([dbc.Input(id='bt-filter-rsi-over', value=70, style=STYLE_INPUT)], width=4),
                            dbc.Col([dbc.Input(id='bt-filter-rsi-under', value=30, style=STYLE_INPUT)], width=4)
                        ])
                    ])
                ], style=STYLE_CARD)
                
            ], width=12, md=4),

            # --- RIGHT COLUMN: VISUALIZATION ---
            dbc.Col([
                # 1. SUMMARY METRICS
                dbc.Card([
                    dbc.CardHeader("MISSION REPORT", style=STYLE_HEADER),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.H6("FINAL BALANCE", style={'color': THEME['TEXT_GOLD']}), html.H3(id='bt-res-balance', children="--", style={'color': '#fff'})], className="text-center"),
                            dbc.Col([html.H6("NET RETURN", style={'color': THEME['TEXT_GOLD']}), html.H3(id='bt-res-return', children="--", style={'color': '#fff'})], className="text-center"),
                            dbc.Col([html.H6("TOTAL TRADES", style={'color': THEME['TEXT_GOLD']}), html.H3(id='bt-res-sig-avg', children="--", style={'color': '#fff'})], className="text-center"),
                        ], className="text-center mb-3"),
                        html.Hr(style={'borderColor': '#fff', 'opacity': '0.2'}),
                        dbc.Row([
                            dbc.Col([html.H6("DRAWDOWN", style={'color': THEME['TEXT_ACCENT']}), html.H4(id='bt-res-dd', children="--", style={'color': '#fff'})], className="text-center"),
                            dbc.Col([html.H6("AVG DURATION", style={'color': THEME['TEXT_ACCENT']}), html.H4(id='bt-res-duration', children="--", style={'color': '#fff'})], className="text-center"),
                            dbc.Col([html.H6("DOMINANCE", style={'color': THEME['TEXT_ACCENT']}), html.H4(id='bt-res-bias', children="--", style={'color': '#fff'})], className="text-center"),
                        ]),
                    ])
                ], style=STYLE_CARD),

                # 2. EQUITY CURVE
                dbc.Card([
                    dbc.CardHeader("EQUITY TRAJECTORY", style=STYLE_HEADER),
                    dbc.CardBody([
                        dcc.Loading(dcc.Graph(id='bt-equity-chart', style={'height': '350px'})),
                        html.Div(id='bt-status-area', children=get_status_ui("ready"), className="mb-4 mt-3"),
                    ])
                ], style=STYLE_CARD),

                # 3. LEDGER
                dbc.Card([
                    dbc.CardHeader("TRANSACTION LEDGER", style=STYLE_HEADER),
                    dbc.CardBody([
                        html.Div(id='bt-trade-table', style={'overflowY': 'scroll', 'height': '500px'})
                    ], className="p-0")
                ], style=STYLE_CARD)

            ], width=12, lg=8)
        ])
    ], fluid=True)

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback([Output('bt-date-range', 'start_date'), Output('bt-date-range', 'end_date')], Input('bt-date-profile', 'value'))
def update_dates_from_profile(profile_name):
    profile = DATE_PROFILES.get(profile_name)
    if not profile: return no_update, no_update
    return profile.start_date, profile.end_date

@callback(Output('bt-commission', 'disabled'), Input('bt-fee-model', 'value'))
def toggle_commission_input(fee_model): return fee_model != 'MANUAL'

@callback(
    [Output('bt-res-balance', 'children'), Output('bt-res-return', 'children'),
     Output('bt-res-sig-avg', 'children'), Output('bt-res-dd', 'children'),
     Output('bt-res-duration', 'children'), Output('bt-res-bias', 'children'),
     Output('bt-equity-chart', 'figure'), 
     Output('bt-trade-table', 'children'), Output('bt-status-area', 'children')],
    [Input('btn-run-backtest', 'n_clicks')],
    [State('bt-date-range', 'start_date'), State('bt-date-range', 'end_date'),
     State('bt-balance', 'value'), State('bt-mode', 'value'),
     State('bt-tax-rate', 'value'), State('bt-trail-pct', 'value'),
     State('bt-ideal-gain', 'value'), State('bt-be-trigger', 'value'),
     State('bt-selection', 'value'), 
     State('bt-slippage', 'value'), State('bt-commission', 'value'),
     State('bt-fee-model', 'value'), 
     State('bt-filter-sma', 'value'), State('bt-filter-rsi-p', 'value'),
     State('bt-filter-rsi-over', 'value'), State('bt-filter-rsi-under', 'value'),
     State('bt-filter-sma-on', 'value')]
)
def update_backtest(n, start, end, balance, mode, tax, trail, gain, be_trigger, selection, slip, comm, fee_model, sma_p, rsi_p, rsi_over, rsi_under, sma_on):
    if not n: return dash.no_update
    
    # Chart Styling
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    try:
        args = BacktestArgs(start, end, balance, mode, tax, trail, gain, be_trigger, selection, slip, comm, fee_model, sma_p, rsi_over, rsi_under)
        args.sma_filter_on = True if sma_on and sma_on[0] else False
        args.rsi_period = rsi_p
        
        results = engine_backtest.run_backtest_session(
            initial_balance=args.start_balance,
            start_date=args.start_date,
            end_date=args.end_date,
            selection_mode=args.selection_mode,
            strategy_mode=mode 
        )
        
        if results is None or results.empty:
            return "--", "--", "--", "--", "--", "--", empty_fig, [], get_status_ui("failure", "No trades found.")

        save_simulation_to_vault(results)

        def clean_money(s): return float(str(s).replace('$','').replace(',',''))
        results['clean_bal'] = results['Balance'].apply(clean_money)
        results['clean_pnl'] = results['PnL'].apply(clean_money)
        
        final_balance = results.iloc[-1]['clean_bal']
        net_return_pct = ((final_balance - args.start_balance) / args.start_balance) * 100
        cum_max = results['clean_bal'].cummax()
        max_dd = ((results['clean_bal'] - cum_max) / cum_max).min() * 100
        
        call_count = len(results[results['Type'] == 'CALL'])
        put_count = len(results[results['Type'] == 'PUT'])
        if len(results) > 0:
            call_pct = int((call_count/len(results))*100)
            put_pct = int((put_count/len(results))*100)
            if call_count > put_count: bias_disp = f"CALLS ({call_pct}%)"
            elif put_count > call_count: bias_disp = f"PUTS ({put_pct}%)"
            else: bias_disp = "BALANCED"
        else: bias_disp = "--"
        
        # Chart
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(x=results['Date'], y=results['clean_bal'], mode='lines', line=dict(color=THEME['SUCCESS'], width=2), fill='tozeroy', name='Equity'))
        fig_eq.update_layout(template="plotly_dark", margin=dict(l=40, r=40, t=20, b=40), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, font=dict(color='#fff'))

        # Table
        table_rows = []
        for i, r in results.iterrows():
            pnl_val = clean_money(r['PnL'])
            table_rows.append(html.Tr([
                html.Td(r['Date'], style={'color': '#fff'}), 
                html.Td(r['Time'], style={'color': '#fff'}), 
                html.Td(r.get('Exit_Time', '--'), style={'color': '#ccc'}), 
                html.Td(r['Type'], style={'color': THEME['TEXT_ACCENT'] if r['Type']=='CALL' else THEME['DANGER'], 'fontWeight': 'bold'}), 
                html.Td("60m", style={'color': '#ccc'}), 
                html.Td(r['Entry'], style={'color': '#fff'}), 
                html.Td(r['Exit'], style={'color': '#fff'}), 
                html.Td(r['PnL'], style={'color': THEME['SUCCESS'] if pnl_val>=0 else THEME['DANGER'], 'fontWeight': 'bold'}), 
                html.Td(r['Return'], style={'color': THEME['SUCCESS'] if pnl_val>=0 else THEME['DANGER']})
            ], style={'backgroundColor': 'rgba(0,0,0,0.2)', 'borderBottom': '1px solid #333'}))
            
        tbl = dbc.Table([html.Thead(html.Tr([html.Th("DATE"),html.Th("ENTRY"),html.Th("EXIT"),html.Th("TYPE"),html.Th("DUR"),html.Th("IN $"),html.Th("OUT $"),html.Th("PnL"),html.Th("ROI")]))] + [html.Tbody(table_rows)], bordered=False, hover=True, size="sm")

        return f"${final_balance:,.2f}", html.Span(f"{net_return_pct:+.1f}%", style={'color': THEME['SUCCESS'] if net_return_pct > 0 else THEME['DANGER']}), f"{len(results)}", f"{max_dd:.1f}%", "60m", html.Span(bias_disp, style={'color': THEME['TEXT_ACCENT']}), fig_eq, tbl, get_status_ui("success", f"Sim Complete: {len(results)} Trades")
        
    except Exception as e:
        traceback.print_exc()
        return "--", "--", "--", "--", "--", "--", empty_fig, [], get_status_ui("crash", str(e))