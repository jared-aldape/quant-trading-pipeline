import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from src.core import engine_forecast

# ==============================================================================
# RENDER LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("THE PROPHET (Predictive Modeling)", className="display-6 fw-bold text-white"),
                html.Hr(className="my-2")
            ], width=12)
        ], className="mb-4"),

        # CONTROL PANEL
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("MODEL CONFIG", className="fw-bold text-info", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        html.Label("Target Asset", className="text-white"),
                        dbc.Input(id="fc-ticker", type="text", value="SPY", className="mb-3"),
                        
                        html.Label("Model Type", className="text-white"),
                        dcc.Dropdown(
                            id="fc-model-type", # Added ID
                            options=[
                                {'label': 'Statistical Volatility (ORB)', 'value': 'ORB'},
                                {'label': 'Linear Regression (Trend Channel)', 'value': 'LIN'} # ENABLED
                            ],
                            value='ORB',
                            clearable=False,
                            className="mb-3",
                            style={'color': '#000'}
                        ),
                        
                        dbc.Button("🔮 GENERATE FORECAST", id="btn-run-forecast", color="primary", className="w-100 fw-bold")
                    ], style={'backgroundColor': '#0a0a0a'})
                ], className="shadow mb-4", style={'border': '1px solid #333'}),
                
                # KPI RESULTS
                html.Div(id="fc-kpi-area")
                
            ], width=12, md=4),

            # VISUALIZATION
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("PROJECTION CONE", className="fw-bold text-white", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id="fc-chart", style={'height': '450px'}))
                    )
                ], className="shadow", style={'backgroundColor': '#000', 'border': '1px solid #333'})
            ], width=12, md=8)
        ])

    ], fluid=True, style={'backgroundColor': '#000', 'minHeight': '100vh'})

# ==============================================================================
# CALLBACKS
# ==============================================================================
@callback(
    [Output("fc-kpi-area", "children"),
     Output("fc-chart", "figure")],
    [Input("btn-run-forecast", "n_clicks")],
    [State("fc-ticker", "value"), State("fc-model-type", "value")] # ADDED MODEL STATE
)
def update_forecast(n, ticker, model_type):
    if not n:
        return "", go.Figure().update_layout(template="plotly_dark", title="Awaiting Command...", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    # PASS MODEL TYPE
    result = engine_forecast.generate_forecast(ticker, model_type)
    
    if not result or result['status'] != "ACTIVE":
        err_msg = result.get('msg', 'Unknown Error') if result else "Connection Failed"
        return dbc.Alert(f"Prediction Failed: {err_msg}", color="warning"), go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

    # 1. BUILD KPI CARDS
    mid_label = "REGRESSION MID" if result.get('type') == 'LIN' else "ORB HIGH"
    low_label = "2-SIGMA LOW" if result.get('type') == 'LIN' else "ORB LOW"

    kpi = dbc.Card([
        dbc.CardBody([
            html.H5(f"{result['trend']}", className="text-warning text-center mb-4"),
            dbc.Row([
                dbc.Col([html.Small("TARGET HIGH"), html.H3(f"${result['proj_high']:.2f}", className="text-success")], width=6, className="text-center"),
                dbc.Col([html.Small("TARGET LOW"), html.H3(f"${result['proj_low']:.2f}", className="text-danger")], width=6, className="text-center"),
            ]),
            html.Hr(style={'borderColor': '#444'}),
            dbc.Row([
                dbc.Col([html.Small(mid_label), html.H5(f"${result['orb_high']:.2f}")], width=6),
                dbc.Col([html.Small(low_label), html.H5(f"${result['orb_low']:.2f}")], width=6),
            ], className="text-center text-muted")
        ])
    ], color="#1a1a1a", inverse=True, className="border-info")

    # 2. BUILD CHART
    df = result['dataframe']
    fig = go.Figure()
    
    # Price Action
    fig.add_trace(go.Candlestick(
        x=df['datetime'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name='Price', increasing_line_color='#00bc8c', decreasing_line_color='#e74c3c'
    ))
    
    # Linear Regression Specifics
    if result.get('type') == 'LIN':
        fig.add_trace(go.Scatter(x=df['datetime'], y=df['reg_line'], mode='lines', line=dict(color='yellow', width=1, dash='dash'), name='Regression'))
        fig.add_trace(go.Scatter(x=df['datetime'], y=df['upper_band'], mode='lines', line=dict(color='#00bc8c', width=1), name='+2 Sigma'))
        fig.add_trace(go.Scatter(x=df['datetime'], y=df['lower_band'], mode='lines', line=dict(color='#e74c3c', width=1), name='-2 Sigma'))
    else:
        # ORB Lines
        fig.add_hline(y=result['proj_high'], line_dash="dot", line_color="#00bc8c", annotation_text="Proj HIGH")
        fig.add_hline(y=result['proj_low'], line_dash="dot", line_color="#e74c3c", annotation_text="Proj LOW")
        fig.add_hline(y=result['orb_high'], line_dash="dash", line_color="gray", annotation_text="ORB High")
        fig.add_hline(y=result['orb_low'], line_dash="dash", line_color="gray", annotation_text="ORB Low")

    fig.update_layout(
        template="plotly_dark",
        title=f"{ticker} Forecast ({model_type})",
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis_rangeslider_visible=False,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color="white"),
        yaxis=dict(gridcolor='#333'), xaxis=dict(gridcolor='#333')
    )

    return kpi, fig