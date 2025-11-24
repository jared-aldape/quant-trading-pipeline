import dash
from dash import dcc, html, Input, Output, State, register_page, callback, ctx
import plotly.graph_objects as go
import duckdb
import pandas as pd
from datetime import timedelta
from src.utils import config

register_page(__name__, path='/simulator', name='Simulator')

# Reuse logic from 08/13 for brevity
def get_sim_events():
    con = duckdb.connect(str(config.DB_FILE))
    try:
        df = con.execute(f"SELECT date, entry_timestamp_utc, xsp_price FROM {config.TBL_MANIFEST} ORDER BY date DESC").df()
        con.close()
        return [{'label': f"{r['date']} | ${r['xsp_price']:.0f}", 'value': r['entry_timestamp_utc']} for _, r in df.iterrows()]
    except: return []

layout = html.Div([
    html.H2("🕹️ Flight Simulator", style={'color': 'white', 'textAlign': 'center'}),
    
    html.Div([
        dcc.Dropdown(id='sim-event', options=get_sim_events(), placeholder="Select Session", style={'color': '#000'}),
        html.Br(),
        html.Button('▶ Play', id='sim-play', className='btn btn-success', style={'marginRight': '10px'}),
        html.Button('⏸ Pause', id='sim-pause', className='btn btn-warning'),
        dcc.Slider(id='sim-slider', min=0, max=390, step=5, value=0, marks={0:'Open', 390:'Close'}),
    ], style={'padding': '20px', 'backgroundColor': '#222', 'borderRadius': '10px', 'margin': '20px'}),
    
    dcc.Graph(id='sim-graph', style={'height': '600px'}),
    dcc.Interval(id='sim-ticker', interval=1000, disabled=True)
])

@callback(
    Output('sim-ticker', 'disabled'),
    [Input('sim-play', 'n_clicks'), Input('sim-pause', 'n_clicks')]
)
def toggle_sim(play, pause):
    if ctx.triggered_id == 'sim-play': return False
    return True

@callback(
    Output('sim-slider', 'value'),
    [Input('sim-ticker', 'n_intervals')],
    [State('sim-slider', 'value')]
)
def advance_sim(n, val):
    return val + 5 if val < 390 else val

@callback(
    Output('sim-graph', 'figure'),
    [Input('sim-event', 'value'), Input('sim-slider', 'value')]
)
def update_sim_view(event, mins):
    if not event: return go.Figure()
    
    # Mock visual for migration proof
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark", 
        title=f"Simulation T+{mins} mins (Data connection required for full detail)",
        xaxis={'title': 'Time'}, yaxis={'title': 'Price'}
    )
    return fig