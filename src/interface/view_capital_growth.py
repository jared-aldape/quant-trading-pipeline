import dash
from dash import dcc, html, dash_table, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import pathlib
import sys
import math
from datetime import date, timedelta, datetime
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

# PATH SETUP
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_forensics as forensics
from src.utils import config

# ==============================================================================
# 1. CORE LOGIC
# ==============================================================================
def get_business_days(start_date, days_forward=252):
    """Generates valid US business days."""
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    rng = pd.date_range(start=start_date, periods=days_forward, freq=us_bd)
    return rng

def calculate_projection(start_bal, daily_rate_pct, tax_rate_pct, start_date, target_goal=None, history_df=None):
    """
    Generates projection with 'Stop at Goal' logic and 'Low Balance' safety.
    """
    # ⚡ SAFETY: Handle low/zero balance
    if start_bal is None or start_bal <= 0: start_bal = 100.0
    
    days = 252 * 2 # Cap at 2 years max calculation
    daily_rate = daily_rate_pct / 100.0
    tax_rate = tax_rate_pct / 100.0
    
    dates = get_business_days(start_date, days)
    
    data = []
    current_bal = start_bal
    goal_reached = False
    
    # 1. Build Base Target Projection
    for i, d in enumerate(dates):
        day_num = i + 1
        gain = current_bal * daily_rate
        end_bal = current_bal + gain
        
        tax_liability = (end_bal - start_bal) * tax_rate
        net_profit = (end_bal - start_bal) - tax_liability
        
        row = {
            'Day': day_num,
            'Date': d,
            'BeginBal': current_bal,
            'TargetGain': gain,
            'ProjectedBal': end_bal,
            'TaxLiability': max(0, tax_liability), # No negative tax
            'TakeHome': start_bal + net_profit
        }
        data.append(row)
        current_bal = end_bal 
        
        # ⚡ STOP AT GOAL LOGIC
        if target_goal and end_bal >= target_goal:
            goal_reached = True
            break
        
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Pre-Initialize Columns
    df['ActualBal'] = np.nan
    df['Variance'] = 0.0
    
    # 2. Merge Actual History (If Exists)
    if history_df is not None and not history_df.empty:
        try:
            # Normalize
            history_df['Date'] = pd.to_datetime(history_df['entry_time']).dt.normalize()
            
            # Aggregate Daily PnL
            daily_pnl = history_df.groupby('Date')['pnl'].sum().reset_index()
            
            # Filter for relevant dates (start_date onwards)
            daily_pnl = daily_pnl[daily_pnl['Date'] >= pd.Timestamp(start_date)]
            
            if not daily_pnl.empty:
                # Cumulative Actual Balance
                daily_pnl['CumulativePnL'] = daily_pnl['pnl'].cumsum()
                daily_pnl['ActualBal_Calc'] = start_bal + daily_pnl['CumulativePnL']
                
                # Merge
                df = df.merge(daily_pnl[['Date', 'ActualBal_Calc']], on='Date', how='left')
                
                if 'ActualBal_Calc' in df.columns:
                    df['ActualBal'] = df['ActualBal_Calc'].combine_first(df['ActualBal'])
                    df = df.drop(columns=['ActualBal_Calc'])
                
                # Forward Fill Actuals for gap days
                df['ActualBal'] = df['ActualBal'].ffill()
                
                # Calculate Variance (Only where Actual exists)
                df['Variance'] = np.where(df['ActualBal'].notnull(), df['ActualBal'] - df['ProjectedBal'], 0.0)
                
        except Exception as e:
            print(f"Projection Merge Error: {e}")
            
    return df, goal_reached

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW ---
        dbc.Row([
            dbc.Col([
                html.H2("CAPITAL LAB COMMAND", className="magitek-h2"),
                html.P("COMPOUND GROWTH | TAX SIMULATOR | REALITY CHECK", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: PROJECTION", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9", "backgroundColor": "#283878", "color": "#f3f5f9"}),

        # CONTROLS & KPIs
        dbc.Row([
            # INPUT CARD
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("PARAMETERS", className="card-header"),
                    dbc.CardBody([
                        # ROW 1: MONEY
                        dbc.Row([
                            dbc.Col([
                                html.Label("START CAPITAL ($)", className="small text-muted font-monospace"),
                                dbc.Input(id='cap-start', type='number', value=2000, step=100, className="mb-2", style={"fontFamily": "monospace"})
                            ], width=6),
                            dbc.Col([
                                html.Label("TARGET GOAL ($)", className="small text-muted font-monospace"),
                                dbc.Input(id='cap-goal', type='number', value=25000, step=1000, className="mb-2", style={"fontFamily": "monospace"})
                            ], width=6),
                        ], className="mb-3"),
                        
                        # ROW 2: RATES
                        dbc.Row([
                            dbc.Col([
                                html.Label("DAILY TARGET (%)", className="small text-muted font-monospace"),
                                dbc.Input(id='cap-rate', type='number', value=2.0, step=0.1, className="mb-2", style={"fontFamily": "monospace"})
                            ], width=6),
                            dbc.Col([
                                html.Label("TAX RATE (%)", className="small text-muted font-monospace"),
                                dbc.Input(id='cap-tax', type='number', value=30.0, step=1.0, className="mb-2", style={"fontFamily": "monospace"})
                            ], width=6),
                        ], className="mb-3"),
                        
                        # ROW 3: DATE
                        dbc.Row([
                            dbc.Col([
                                html.Label("START DATE", className="small text-muted font-monospace"),
                                dcc.DatePickerSingle(
                                    id='cap-date',
                                    date=date.today() - timedelta(days=30), 
                                    className="d-block",
                                    style={"fontFamily": "monospace"}
                                )
                            ], width=12),
                        ], className="mb-3"),
                        
                        html.Hr(className="border-secondary"),
                        
                        # DATA SOURCE
                        html.Label("COMPARISON SOURCE", className="small text-muted font-monospace mb-2"),
                        dcc.Dropdown(
                            id='cap-source',
                            options=[
                                {'label': 'NONE (Pure Sim)', 'value': 'none'},
                                {'label': '🦁 LIVE LEDGER (Robinhood)', 'value': 'rh'},
                                {'label': '⚡ DATA GENERATOR', 'value': 'gen'},
                                {'label': '🎮 MANUAL SIMULATOR', 'value': 'manual'},
                                {'label': '📡 RAW SIGNAL HISTORY', 'value': 'sig'}
                            ],
                            value='none',
                            clearable=False,
                            className="mb-3",
                            style={"fontFamily": "monospace"}
                        ),
                        
                        # DIRECTION FILTER
                        html.Label("FILTER DIRECTION (STRESS TEST)", className="small text-muted font-monospace mb-2"),
                        dbc.RadioItems(
                            id='cap-direction',
                            options=[
                                {'label': 'ALL', 'value': 'ALL'},
                                {'label': 'CALLS', 'value': 'CALL'},
                                {'label': 'PUTS', 'value': 'PUT'},
                            ],
                            value='ALL',
                            inline=True,
                            className="text-white font-monospace"
                        ),

                        dbc.Button("CALCULATE TRAJECTORY", id='cap-btn', color="primary", className="w-100 mt-4 fw-bold font-monospace")
                    ])
                ], className="shadow h-100", style={"backgroundColor": "#101830", "border": "1px solid #444"})
            ], width=4),

            # KPI OUTPUTS
            dbc.Col([
                dbc.Row(id='cap-kpi-row', className="mb-3"),
                # Large Chart Area
                dbc.Card([
                    dbc.CardHeader("GROWTH TRAJECTORY", className="card-header text-center"),
                    dbc.CardBody(dcc.Graph(id='cap-growth-chart', style={'height': '380px'}, config={'displayModeBar': False}))
                ], className="shadow h-100", style={"backgroundColor": "#101830", "border": "1px solid #444"})
            ], width=8)
        ], className="mb-4"),

        # DETAILED TABLE
        dbc.Row([
            dbc.Col([
                html.H4("PROJECTION LEDGER", className="text-info font-monospace"),
                html.Div(id='cap-table-container')
            ], width=12)
        ])

    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output('cap-kpi-row', 'children'),
     Output('cap-growth-chart', 'figure'),
     Output('cap-table-container', 'children')],
    [Input('cap-btn', 'n_clicks')],
    [State('cap-start', 'value'),
     State('cap-goal', 'value'),
     State('cap-rate', 'value'),
     State('cap-tax', 'value'),
     State('cap-date', 'date'),
     State('cap-source', 'value'),
     State('cap-direction', 'value')]
)
def update_capital_model(n, start_bal, target_goal, daily_rate, tax_rate, start_date, source, direction):
    # ⚡ LOW BALANCE FIX: Ensure start_bal is valid
    if start_bal is None or start_bal <= 0: start_bal = 100.0
    if not target_goal: target_goal = start_bal * 2
    
    # 1. Fetch History
    history_df = pd.DataFrame()
    if source != 'none':
        history_df = forensics.fetch_scorecard_data(source, 'Year To Date')
        
        if not history_df.empty:
            history_df['entry_time'] = pd.to_datetime(history_df['entry_time'])
            history_df = history_df[history_df['entry_time'] >= pd.Timestamp(start_date)]
            if direction != 'ALL':
                history_df = history_df[history_df['ticker'].str.contains(direction, na=False)]

    # 2. Calculate Projection (Stop at Goal Enabled)
    df, goal_reached = calculate_projection(start_bal, daily_rate, tax_rate, start_date, target_goal, history_df)
    
    if df.empty:
        return [], go.Figure(), html.Div("Calculation Error", className="text-danger")

    # 3. Goal Math
    days_to_goal_str = "∞"
    goal_date_str = "Never"
    
    # If already reached, get actual date
    if goal_reached:
        days_to_goal_str = f"{len(df)} Days"
        goal_date_str = df.iloc[-1]['Date'].strftime('%b %d, %Y')
    elif daily_rate > 0 and target_goal > start_bal:
        # Theoretical calculation if not reached in window
        rate_dec = daily_rate / 100.0
        try:
            t_days = math.log(target_goal / start_bal) / math.log(1 + rate_dec)
            t_days_int = int(np.ceil(t_days))
            days_to_goal_str = f"{t_days_int} Days"
        except: pass

    # 4. KPIs
    end_bal = df.iloc[-1]['ProjectedBal']
    tax_bill = df.iloc[-1]['TaxLiability']
    take_home = df.iloc[-1]['TakeHome']
    
    kpis = [
        dbc.Col(dbc.Card([html.H6("PROJECTED END", className="font-monospace"), html.H3(f"${end_bal:,.0f}", className="text-info font-monospace")], body=True, color="dark", inverse=True, style={"border": "1px solid #444"})),
        dbc.Col(dbc.Card([html.H6("GOAL REACHED", className="font-monospace"), html.H3(days_to_goal_str, className="text-success font-monospace"), html.Small(goal_date_str, className="text-muted font-monospace")], body=True, color="dark", inverse=True, style={"border": "1px solid #444"})),
        dbc.Col(dbc.Card([html.H6("EST. TAXES", className="font-monospace"), html.H3(f"${tax_bill:,.0f}", className="text-danger font-monospace")], body=True, color="dark", inverse=True, style={"border": "1px solid #444"})),
        dbc.Col(dbc.Card([html.H6("NET TAKE HOME", className="font-monospace"), html.H3(f"${take_home:,.0f}", className="text-warning font-monospace")], body=True, color="dark", inverse=True, style={"border": "1px solid #444"})),
    ]

    # 5. Chart (With Milestones & Drawdown Sim)
    fig = go.Figure()
    
    # Target Path
    fig.add_trace(go.Scatter(x=df['Date'], y=df['ProjectedBal'], mode='lines', name='Target Path', line=dict(color='#00bc8c', width=3)))
    
    # Drawdown Simulation (Risk Path - 50% of Target)
    fig.add_trace(go.Scatter(x=df['Date'], y=df['ProjectedBal'] * 0.5, mode='lines', name='Risk Path (-50%)', line=dict(color='#e74c3c', width=1, dash='dot'), opacity=0.5))

    # Actuals
    if 'ActualBal' in df.columns and not df['ActualBal'].isna().all():
        fig.add_trace(go.Scatter(x=df['Date'], y=df['ActualBal'], mode='lines+markers', name=f'Actual ({direction})', line=dict(color='#fde722', width=3)))
    
    # Milestones
    if target_goal >= 25000:
        fig.add_hline(y=25000, line_dash="dash", line_color="cyan", annotation_text="PDT ($25k)", annotation_position="bottom right")
    
    fig.add_hline(y=target_goal, line_dash="solid", line_color="#00ff41", annotation_text="GOAL", annotation_position="top right")

    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=40, b=40), 
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"), 
        yaxis_tickprefix="$",
        font=dict(family="'VT323', monospace", size=14, color="#f3f5f9")
    )

    # 6. Table
    df_view = df.copy()
    df_view['Date'] = df_view['Date'].dt.strftime('%Y-%m-%d')
    cols = ['Day', 'Date', 'BeginBal', 'TargetGain', 'ProjectedBal', 'TaxLiability', 'TakeHome']
    if 'ActualBal' in df.columns and not df['ActualBal'].isna().all():
        cols.insert(5, 'ActualBal')
        cols.insert(6, 'Variance')
    for c in cols[2:]:
        if c in df_view.columns:
            df_view[c] = df_view[c].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "-")

    # MAGITEK TABLE STYLES
    header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9', 'fontWeight': 'bold'}
    cell_style = {'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'}

    tbl = dash_table.DataTable(
        data=df_view[cols].to_dict('records'),
        columns=[{'name': i, 'id': i} for i in cols],
        style_header=header_style,
        style_cell=cell_style,
        style_data_conditional=[
            {'if': {'filter_query': '{Variance} contains "$"', 'column_id': 'Variance'}, 'color': '#00ff41'}, 
            {'if': {'filter_query': '{Variance} contains "-"', 'column_id': 'Variance'}, 'color': '#ff5555'}, 
        ],
        page_size=10, style_table={'overflowX': 'auto'}
    )

    return kpis, fig, tbl