import dash
from dash import dcc, html, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
from src.core import engine_forensics

# ==============================================================================
# RENDER LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("FORENSICS LAB", className="display-6 fw-bold text-white"),
                html.Small("Post-Trade Audit & Statistical Breakdown", className="text-muted"),
                html.Hr(className="my-2", style={'borderColor': '#444'})
            ], width=12)
        ], className="mb-4"),

        # CONTROL PANEL
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("CASE FILE SELECTOR (DB)", className="fw-bold text-info", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        html.Label("Select Simulation Run", className="text-white"),
                        dcc.Dropdown(
                            id='audit-run-selector',
                            options=engine_forensics.fetch_simulation_runs(),
                            placeholder="Select a Backtest Run...",
                            className="mb-2",
                            style={'color': '#000'}
                        ),
                        dbc.Button("↻ REFRESH DB", id='audit-refresh-btn', color="secondary", outline=True, size="sm", className="w-100")
                    ], style={'backgroundColor': '#131722'})
                ], className="shadow mb-4", style={'border': '1px solid #444'})
            ], width=12, md=4),
            
            # SUMMARY STATS (Placeholder)
            dbc.Col([
                html.Div(id='audit-stats-panel')
            ], width=12, md=8)
        ]),

        # VISUALIZATION GRID
        dbc.Row([
            # ROW 1: DECAY & DOMINANCE
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("SIGNAL DECAY (Profit by Sequence)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-decay', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=8),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("DOMINANCE (Call vs Put)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-dominance', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=4),
        ], className="mb-4"),

        # ROW 2: KILL ZONES & THETA
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("KILL ZONE (Hourly Performance)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-killzone', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=6),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("THETA RISK (Duration vs P&L)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-theta', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=6),
        ])

    ], fluid=True, style={'backgroundColor': '#000', 'minHeight': '100vh', 'padding': '20px'})

# ==============================================================================
# CALLBACKS
# ==============================================================================
@callback(
    [Output('audit-run-selector', 'options'),
     Output('chart-decay', 'figure'),
     Output('chart-dominance', 'figure'),
     Output('chart-killzone', 'figure'),
     Output('chart-theta', 'figure')],
    [Input('audit-run-selector', 'value'),
     Input('audit-refresh-btn', 'n_clicks')]
)
def update_forensics(run_id, n_clicks):
    # 1. Refresh Dropdown
    options = engine_forensics.fetch_simulation_runs()
    
    # 2. Base Charts (Empty)
    empty_fig = go.Figure().update_layout(
        template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color="white"), xaxis={'showgrid': False, 'visible': False}, yaxis={'showgrid': False, 'visible': False}
    )
    
    if not run_id:
        return options, empty_fig, empty_fig, empty_fig, empty_fig

    # 3. Fetch Data
    df = engine_forensics.fetch_run_metrics(run_id)
    if df.empty:
        return options, empty_fig, empty_fig, empty_fig, empty_fig

    # --- CHART 1: SIGNAL DECAY (Cumulative P&L) ---
    df['cum_pnl'] = df['pnl'].cumsum()
    fig_decay = go.Figure()
    fig_decay.add_trace(go.Scatter(x=df['trade_seq'], y=df['cum_pnl'], mode='lines+markers', line=dict(color='#00bc8c', width=2), marker=dict(size=4)))
    fig_decay.update_layout(
        template="plotly_dark", title="Equity Curve (Sequence)", margin=dict(l=40, r=40, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        yaxis=dict(gridcolor='#333'), xaxis=dict(gridcolor='#333')
    )

    # --- CHART 2: DOMINANCE (Win Rate by Type) ---
    win_rates = df[df['pnl'] > 0].groupby('type').size()
    total_counts = df.groupby('type').size()
    wr_pct = (win_rates / total_counts * 100).fillna(0)
    
    fig_dom = go.Figure()
    fig_dom.add_trace(go.Bar(x=wr_pct.index.str.upper(), y=wr_pct.values, marker_color=['#00d2ff', '#f39c12']))
    fig_dom.update_layout(
        template="plotly_dark", title="Win Rate % by Type", margin=dict(l=40, r=40, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        yaxis=dict(range=[0, 100], gridcolor='#333')
    )

    # --- CHART 3: KILL ZONE (Hourly P&L) ---
    hourly_pnl = df.groupby('hour')['pnl'].sum().reset_index()
    colors = ['#00bc8c' if v >= 0 else '#ef5350' for v in hourly_pnl['pnl']]
    
    fig_kill = go.Figure()
    fig_kill.add_trace(go.Bar(x=hourly_pnl['hour'], y=hourly_pnl['pnl'], marker_color=colors))
    fig_kill.update_layout(
        template="plotly_dark", title="Net P&L by Hour of Day", margin=dict(l=40, r=40, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        xaxis=dict(tickmode='linear', dtick=1, gridcolor='#333'), yaxis=dict(gridcolor='#333')
    )

    # --- CHART 4: THETA RISK (Duration vs ROI) ---
    fig_theta = go.Figure()
    fig_theta.add_trace(go.Scatter(
        x=df['duration'], y=df['return_pct'], 
        mode='markers', 
        marker=dict(
            size=8, 
            color=df['return_pct'], 
            colorscale='RdYlGn', 
            cmid=0,
            line=dict(width=1, color='#333')
        )
    ))
    fig_theta.update_layout(
        template="plotly_dark", title="Duration (Mins) vs ROI %", margin=dict(l=40, r=40, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        xaxis=dict(title="Minutes Held", gridcolor='#333'), yaxis=dict(title="Return %", gridcolor='#333')
    )

    return options, fig_decay, fig_dom, fig_kill, fig_theta