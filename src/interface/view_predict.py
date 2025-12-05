import dash
from dash import dcc, html, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz
from src.core import engine_simulator, engine_ml
from src.utils import config

# ==============================================================================
# 1. PREDICTIVE MATH (ORB + LINREG)
# ==============================================================================
def calculate_orb(df):
    """Calculates Opening Range Breakout (09:30-10:00) levels."""
    if df is None or df.empty: return None, None
    
    # Filter for RTH start
    df['time'] = df['Datetime'].dt.time
    start = time(9, 30)
    end = time(10, 0)
    
    orb_df = df[(df['time'] >= start) & (df['time'] < end)]
    if orb_df.empty: return None, None
    
    return orb_df['High'].max(), orb_df['Low'].min()

def calculate_linreg(df):
    """Calculates Linear Regression Channel."""
    if df is None or len(df) < 20: return df
    
    df['x'] = np.arange(len(df))
    # Fit line
    slope, intercept = np.polyfit(df['x'], df['Close'], 1)
    df['reg_line'] = slope * df['x'] + intercept
    
    # Std Dev Bands
    std = df['Close'].std()
    df['upper_band'] = df['reg_line'] + (2 * std)
    df['lower_band'] = df['reg_line'] - (2 * std)
    
    return df

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("PREDICTIVE ANALYSIS (The HUD)", className="display-6 fw-bold text-white"),
                html.P("Project Echo (ORB) and Project Delta (LinReg) visualization.", className="text-muted lead")
            ], width=8),
            dbc.Col([
                html.Div(id='predict-clock', className="display-6 text-end text-info font-monospace")
            ], width=4)
        ], className="mb-3"),

        dbc.Row([
            # ORACLE PANEL
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("🤖 ORACLE CONFIDENCE", className="fw-bold text-warning", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        html.H4(id='predict-oracle-call', className="text-center mb-2"),
                        html.H4(id='predict-oracle-put', className="text-center")
                    ])
                ], className="shadow mb-3")
            ], width=3),
            
            # CHART
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dcc.Graph(id='predict-chart', style={'height': '600px'}, config={'displayModeBar': False})
                    ], className="p-1", style={'backgroundColor': '#000'})
                ], className="shadow")
            ], width=9)
        ]),

        dcc.Interval(id='predict-interval', interval=30000, n_intervals=0) # 30s update

    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output('predict-chart', 'figure'),
     Output('predict-oracle-call', 'children'),
     Output('predict-oracle-put', 'children'),
     Output('predict-clock', 'children')],
    [Input('predict-interval', 'n_intervals')]
)
def update_prediction_hud(n):
    # 1. Data
    df = engine_simulator.get_live_chart_data(period="1d", interval="1m")
    vix_val, vix_rsi = engine_simulator.get_vix_metrics()
    
    # 2. Oracle
    p_call = engine_ml.predict_success("CALL", vix_val, vix_rsi)
    p_put = engine_ml.predict_success("PUT", vix_val, vix_rsi)
    
    call_style = {'color': '#00bc8c' if p_call > 60 else '#555'}
    put_style = {'color': '#e74c3c' if p_put > 60 else '#555'}
    
    call_disp = html.Span(f"CALL: {p_call}%", style=call_style)
    put_disp = html.Span(f"PUT: {p_put}%", style=put_style)

    # 3. Chart Prep
    fig = go.Figure()
    
    if df is not None and not df.empty:
        # LinReg
        df = calculate_linreg(df)
        
        # Candles
        fig.add_trace(go.Candlestick(
            x=df['Datetime'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name="SPY", increasing_line_color='#00bc8c', decreasing_line_color='#e74c3c'
        ))
        
        # LinReg Channels
        fig.add_trace(go.Scatter(x=df['Datetime'], y=df['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"))
        fig.add_trace(go.Scatter(x=df['Datetime'], y=df['upper_band'], line=dict(color='cyan', width=1), name="+2σ"))
        fig.add_trace(go.Scatter(x=df['Datetime'], y=df['lower_band'], line=dict(color='cyan', width=1), name="-2σ"))
        
        # ORB Levels (Project Echo)
        orb_h, orb_l = calculate_orb(df)
        if orb_h:
            fig.add_hline(y=orb_h, line_color="#00bc8c", line_width=1, line_dash="dash", annotation_text="ORB HIGH")
            fig.add_hline(y=orb_l, line_color="#e74c3c", line_width=1, line_dash="dash", annotation_text="ORB LOW")

    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=20, b=40), 
        xaxis_rangeslider_visible=False,
        uirevision='predict_chart'
    )

    return fig, call_disp, put_disp, datetime.now().strftime("%H:%M")