import sys
import os
import dash
from dash import dcc, html, Input, Output, State, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
from datetime import date
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File is in: src/tools/12_forecast.py
# .parents[0] = tools
# .parents[1] = src
# .parents[2] = PROJECT ROOT
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

logger = get_logger("Forecaster")

# ==============================================================================
# 2. MPA PAGE REGISTRATION
# ==============================================================================
register_page(__name__, path='/forecast', name='Forecaster')

# ==============================================================================
# 3. LOGIC (Risk Buckets & Trajectory)
# ==============================================================================
def get_trading_days(start_date, end_date):
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return pd.date_range(start=start_date, end=end_date, freq=us_bd)

def calculate_trajectory(start_date, end_date, start_bal, roi_goal_pct, tax_rate, stop_period, max_dd_pct):
    """
    Simulates wealth trajectory with periodic Stop Loss events (Risk Buckets).
    """
    dates = get_trading_days(start_date, end_date)
    history = []
    balance = start_bal
    risk_bucket_counter = 0
    total_tax_paid = 0
    
    for d in dates:
        risk_bucket_counter += 1
        # Logic: If we hit the stop period limit, force a loss day
        is_loss_day = (risk_bucket_counter >= stop_period)
        
        if is_loss_day:
            risk_bucket_counter = 0 # Reset bucket
            gross_gain = balance * -(max_dd_pct / 100.0)
            tax_deduction = 0.0 
            net_gain = gross_gain
            risk_label = "🛑 STOP HIT"
        else:
            gross_gain = balance * (roi_goal_pct / 100.0)
            tax_deduction = gross_gain * (tax_rate / 100.0)
            total_tax_paid += tax_deduction
            net_gain = gross_gain - tax_deduction
            risk_label = "✅ GAIN"

        new_balance = balance + net_gain
        history.append({
            "Date": d, 
            "Start Balance": balance, 
            "Net Gain": net_gain, 
            "End Balance": new_balance, 
            "Risk Label": risk_label, 
            "Is Loss": is_loss_day
        })
        balance = new_balance

    return pd.DataFrame(history), total_tax_paid

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
layout = dbc.Container([
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 2", className="text-muted mb-0"),
            html.H2("RISK BUCKET FORECASTER", className="display-6 fw-bold text-success"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    # CONTROLS & CHART
    dbc.Row([
        # LEFT COL: PARAMETERS
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("SIMULATION PARAMETERS", className="fw-bold text-success"),
                dbc.CardBody([
                    html.Label("Projection Period"),
                    dcc.DatePickerRange(
                        id='fc-date-range', 
                        start_date=date.today(), 
                        end_date=date.today() + pd.Timedelta(days=60), 
                        className="mb-3 w-100"
                    ),
                    
                    dbc.Row([
                        dbc.Col([html.Label("Start Capital ($)"), dbc.Input(id='fc-start', type='number', value=2500, step=100)], width=6),
                        dbc.Col([html.Label("Daily ROI Goal (%)"), dbc.Input(id='fc-roi', type='number', value=10, step=1)], width=6),
                    ], className="mb-3"),
                    
                    dbc.Row([
                        dbc.Col([html.Label("Tax Rate (%)"), dbc.Input(id='fc-tax', type='number', value=26.8, step=0.1)], width=6),
                        dbc.Col([html.Label("Stop Loss % (Drag)"), dbc.Input(id='fc-max-dd', type='number', value=30, step=5)], width=6),
                    ], className="mb-3"),
                    
                    html.Label("Risk Bucket Size (Days until Stop Loss)"),
                    dcc.Slider(
                        id='fc-stop-period', min=2, max=30, step=1, value=5,
                        marks={2: '2d', 5: '5d', 10: '10d', 20: '20d', 30: '30d'},
                        className="mb-4"
                    ),
                    
                    dbc.Button("🚀 RUN PROJECTION", id='fc-run-btn', color="success", className="w-100 fw-bold")
                ])
            ], className="shadow mb-3")
        ], width=12, lg=4),

        # RIGHT COL: VISUALIZATION
        dbc.Col([
            # SUMMARY CARDS
            dbc.Row([
                dbc.Col(dbc.Card([
                    dbc.CardBody([html.H6("Total Tax Paid", className="text-muted"), html.H3(id='fc-tax-display', className="text-warning")])
                ], className="mb-3"), width=6),
                dbc.Col(dbc.Card([
                    dbc.CardBody([html.H6("Final Net Balance", className="text-muted"), html.H3(id='fc-final-display', className="text-success")])
                ], className="mb-3"), width=6),
            ]),
            
            # CHART
            dbc.Card([
                dbc.CardBody([
                    dcc.Graph(id='fc-chart', style={'height': '400px'})
                ], className="p-1")
            ], className="shadow mb-3")
        ], width=12, lg=8)
    ]),
    
    # LEDGER TABLE
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("DAILY LEDGER"),
                dbc.CardBody(html.Div(id='fc-ledger-table', style={'maxHeight': '300px', 'overflowY': 'auto'}))
            ], className="shadow")
        ], width=12)
    ])

], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    [Output('fc-chart', 'figure'), 
     Output('fc-tax-display', 'children'), 
     Output('fc-final-display', 'children'),
     Output('fc-ledger-table', 'children')],
    [Input('fc-run-btn', 'n_clicks')],
    [State('fc-date-range', 'start_date'), State('fc-date-range', 'end_date'),
     State('fc-start', 'value'), State('fc-roi', 'value'),
     State('fc-tax', 'value'), State('fc-stop-period', 'value'),
     State('fc-max-dd', 'value')]
)
def update_forecast(n, start_date, end_date, start_bal, roi, tax, stop_period, max_dd):
    if not n:
        return go.Figure(), "$0.00", "$0.00", "Ready to project..."
    
    # 1. Run Logic
    try:
        df, total_tax = calculate_trajectory(start_date, end_date, float(start_bal), float(roi), float(tax), int(stop_period), float(max_dd))
    except Exception as e:
        logger.error(f"Forecast Error: {e}")
        return go.Figure(), "ERR", "ERR", f"Error: {str(e)}"

    # 2. Build Chart (High Contrast)
    fig = go.Figure()
    
    # Main Equity Curve
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['End Balance'], 
        mode='lines+markers', 
        name="Account Balance",
        line=dict(color='#00e676', width=3),
        marker=dict(size=6, color=df['Is Loss'].map({True: '#ff1744', False: '#00e676'})) # Red dots on loss days
    ))
    
    # Principal Line
    fig.add_trace(go.Scatter(
        x=df['Date'], y=[start_bal]*len(df), 
        mode='lines', name="Principal", 
        line=dict(color='#bdbdbd', width=1, dash='dot')
    ))

    fig.update_layout(
        template="plotly_dark",
        title="Projected Equity Curve (Risk Adjusted)",
        yaxis_title="Balance ($)",
        margin=dict(l=40, r=40, t=40, b=40),
        showlegend=False
    )
    
    # 3. Build Table
    table_rows = []
    for _, row in df.iterrows():
        # Highlight loss rows
        row_style = {'backgroundColor': 'rgba(255, 23, 68, 0.1)'} if row['Is Loss'] else {}
        text_style = {'color': '#ff1744', 'fontWeight': 'bold'} if row['Is Loss'] else {'color': '#00e676'}
        
        table_rows.append(html.Tr([
            html.Td(row['Date'].strftime("%Y-%m-%d")),
            html.Td(f"${row['Start Balance']:,.2f}"),
            html.Td(f"{'+' if row['Net Gain'] > 0 else ''}${row['Net Gain']:,.2f}", style=text_style),
            html.Td(f"${row['End Balance']:,.2f}", className="fw-bold"),
            html.Td(row['Risk Label'])
        ], style=row_style))

    table = dbc.Table(
        [html.Thead(html.Tr([html.Th("Date"), html.Th("Start"), html.Th("Net P&L"), html.Th("End Bal"), html.Th("Status")]))] +
        [html.Tbody(table_rows)],
        bordered=True, hover=True, size="sm", className="text-white"
    )

    return fig, f"${total_tax:,.2f}", f"${df.iloc[-1]['End Balance']:,.2f}", table