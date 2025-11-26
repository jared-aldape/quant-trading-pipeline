import sys
import os
import dash
from dash import dcc, html, Input, Output, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import numpy as np
import pandas as pd
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
register_page(__name__, path='/forecast', name='Forecaster')
logger = get_logger("Forecaster")

# ==============================================================================
# 3. HELPER FUNCTIONS (Wealth Projection Logic)
# ==============================================================================
def calculate_growth(start_bal, monthly_contrib, annual_return, years, tax_rate=0.0):
    months = years * 12
    monthly_rate = annual_return / 12 / 100
    
    data = []
    balance = start_bal
    total_contrib = 0
    total_tax = 0
    
    for m in range(1, months + 1):
        # Contribution
        balance += monthly_contrib
        total_contrib += monthly_contrib
        
        # Growth
        growth = balance * monthly_rate
        
        # Tax Drag (Simplified: Taxes paid annually or continuously on gains)
        tax = growth * tax_rate
        net_growth = growth - tax
        total_tax += tax
        
        balance += net_growth
        
        if m % 12 == 0:
            data.append({
                'Year': m // 12,
                'Balance': balance,
                'Contributions': start_bal + total_contrib,
                'Tax Paid': total_tax
            })
            
    return pd.DataFrame(data)

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
layout = dbc.Container([
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 2", className="text-muted mb-0"),
            html.H2("WEALTH FORECASTER", className="display-6 fw-bold text-success"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    # CONTROLS & CHART
    dbc.Row([
        # LEFT COL: CONTROLS
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("GROWTH PARAMETERS", className="fw-bold text-success"),
                dbc.CardBody([
                    html.Label("Starting Balance ($)"),
                    dbc.Input(id='fc-start', type='number', value=10000, step=1000, className="mb-3"),
                    
                    html.Label("Monthly Contribution ($)"),
                    dbc.Input(id='fc-contrib', type='number', value=500, step=100, className="mb-3"),
                    
                    html.Label("Annual Return (%)"),
                    dcc.Slider(id='fc-return', min=1, max=100, step=1, value=25, 
                               marks={10: '10%', 25: '25%', 50: '50%', 100: '100%'}, className="mb-4"),
                    
                    html.Label("Tax Rate (%)"),
                    dcc.Slider(id='fc-tax', min=0, max=50, step=1, value=25, 
                               marks={0: '0%', 15: '15%', 30: '30%', 50: '50%'}, className="mb-4"),
                    
                    html.Label("Time Horizon (Years)"),
                    dcc.Slider(id='fc-years', min=1, max=30, step=1, value=5, 
                               marks={1: '1', 5: '5', 10: '10', 20: '20', 30: '30'}, className="mb-3"),
                ])
            ], className="shadow mb-3")
        ], width=12, md=4),

        # RIGHT COL: CHART
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dcc.Graph(id='fc-chart', style={'height': '500px'})
                ])
            ], className="shadow mb-3")
        ], width=12, md=8)
    ])
], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    Output('fc-chart', 'figure'),
    [Input('fc-start', 'value'), Input('fc-contrib', 'value'),
     Input('fc-return', 'value'), Input('fc-years', 'value'),
     Input('fc-tax', 'value')]
)
def update_forecast(start, contrib, ret, years, tax):
    if not start: start = 0
    if not contrib: contrib = 0
    
    # Calculate Scenarios
    # 1. Base Case (User Input)
    df_base = calculate_growth(start, contrib, ret, years, tax/100)
    
    # 2. Bull Case (+15% Return)
    df_bull = calculate_growth(start, contrib, ret + 15, years, tax/100)
    
    # 3. Bear Case (-10% Return)
    df_bear = calculate_growth(start, contrib, max(ret - 10, 0), years, tax/100)
    
    # PLOT
    fig = go.Figure()
    
    # Fan Chart Style
    fig.add_trace(go.Scatter(
        x=df_bull['Year'], y=df_bull['Balance'], mode='lines', 
        name="Bull Case", line=dict(width=0), showlegend=False
    ))
    
    fig.add_trace(go.Scatter(
        x=df_bear['Year'], y=df_bear['Balance'], mode='lines', 
        name="Bear Case", line=dict(width=0), fill='tonexty', fillcolor='rgba(0, 255, 0, 0.1)', showlegend=False
    ))
    
    fig.add_trace(go.Scatter(
        x=df_base['Year'], y=df_base['Balance'], mode='lines+markers', 
        name="Base Projection", line=dict(color='#00e676', width=4)
    ))
    
    fig.add_trace(go.Scatter(
        x=df_base['Year'], y=df_base['Contributions'], mode='lines', 
        name="Principal", line=dict(color='#bdbdbd', width=2, dash='dot')
    ))

    # Final Labels
    final_bal = df_base.iloc[-1]['Balance']
    fig.add_annotation(
        x=years, y=final_bal, text=f"${final_bal:,.0f}", 
        showarrow=True, arrowhead=1, ax=-40, ay=-40, font=dict(color='#00e676', size=14)
    )

    fig.update_layout(
        template="plotly_dark",
        title="Projected Wealth Curve (Risk Buckets)",
        xaxis_title="Years",
        yaxis_title="Account Balance ($)",
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center")
    )
    
    return fig