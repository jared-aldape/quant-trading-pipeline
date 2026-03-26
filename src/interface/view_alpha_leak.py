# FILE: src/interface/view_alpha_leak.py
# INSTITUTIONAL STANDARD v4.2.1 | FORENSIC LEAK MONITOR (REDESIGNED)

import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import duckdb
import sys
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("UnifiedForensics")

# ==============================================================================
# 2. UI THEME STANDARDS
# ==============================================================================
COLORS = {
    "background": "#0f172a",       
    "panel": "#1e293b",            
    "text_primary": "#f8fafc",     
    "text_secondary": "#94a3b8",   
    "accent_danger": "#ef4444",    
    "accent_success": "#10b981",   
    "border": "#334155",
    "missed_alpha": "#8b5cf6" # Neon Purple for Missed Money
}

LAYOUT_STYLE = {"backgroundColor": COLORS["background"], "minHeight": "100vh", "color": COLORS["text_primary"], "padding": "2rem", "fontFamily": "monospace"}
PANEL_STYLE = {"backgroundColor": COLORS["panel"], "border": f"1px solid {COLORS['border']}", "borderRadius": "8px", "padding": "1.5rem", "boxShadow": "0 4px 6px -1px rgba(0, 0, 0, 0.1)"}

# ==============================================================================
# 3. DATA FORENSICS (FIXED MATH)
# ==============================================================================
def fetch_unified_leak_data(source='rh'):
    if not config.DB_FILE.exists(): return pd.DataFrame()
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    try:
        if source == 'rh':
            base_query = "SELECT root as ticker, entry_time_utc as entry_time, fill_price as entry_price, net_pnl as realized_pnl FROM active_rh_log WHERE status = 'FILLED' AND fill_price > 0"
        elif source == 'sim':
            base_query = "SELECT ticker, entry_time, entry_price, net_pnl as realized_pnl FROM active_simulation_log WHERE source_id != 'BACKTEST'"
        else:
            base_query = "SELECT ticker, entry_time, entry_price, net_pnl as realized_pnl FROM active_simulation_log WHERE source_id = 'BACKTEST'"

        # CRITICAL FIX: We now pull the actual INDEX PRICE at entry, not the option premium.
        query = f"""
        WITH UnifiedTrades AS ({base_query})
        SELECT 
            t.ticker, t.entry_time, t.entry_price, t.realized_pnl,
            (SELECT close FROM indices_1m x WHERE x.ticker = 'XSP' AND x.datetime_utc <= t.entry_time ORDER BY x.datetime_utc DESC LIMIT 1) as index_at_entry,
            (SELECT MAX(high) FROM indices_1m i WHERE i.ticker = 'XSP' AND i.datetime_utc >= t.entry_time AND i.datetime_utc <= t.entry_time + INTERVAL 4 HOUR) as peak_index_price
        FROM UnifiedTrades t
        ORDER BY t.entry_time DESC
        LIMIT 50
        """
        
        df = con.execute(query).df()
        if df.empty: return df

        df['index_at_entry'] = df['index_at_entry'].fillna(0)
        df['peak_index_price'] = df['peak_index_price'].fillna(0)
        
        # The Math: How many actual points did the index move?
        df['points_left'] = df['peak_index_price'] - df['index_at_entry']
        df['points_left'] = df['points_left'].clip(lower=0) # Can't have negative points left
        
        # Missed Profit = Index Points * 100 multiplier * 0.90 Delta floor
        df['missed_profit'] = df['points_left'] * 100 * 0.90
        
        # Formatting for human readability
        df['time_str'] = pd.to_datetime(df['entry_time']).dt.strftime('%m-%d %H:%M')
        df['index_move'] = df['index_at_entry'].round(2).astype(str) + " ➔ " + df['peak_index_price'].round(2).astype(str)
        df['realized_pnl'] = df['realized_pnl'].round(2)
        df['missed_profit'] = df['missed_profit'].round(2)
        
        return df
    except Exception as e:
        log.error(f"Leak Fetch Error: {e}")
        return pd.DataFrame()
    finally:
        con.close()

# ==============================================================================
# 4. DASHBOARD LAYOUT (SIMPLIFIED)
# ==============================================================================
def render():
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.H2("FORENSIC ALPHA LEAK", className="fw-bold mb-0"),
                html.P("WHAT YOU MADE vs. WHAT THE TREND OFFERED", className="text-muted small fw-bold")
            ], width=8),
            dbc.Col([
                dbc.Select(
                    id='leak-source-select',
                    options=[
                        {'label': '🦁 LIVE LEDGER (Robinhood)', 'value': 'rh'},
                        {'label': '✈️ SIMULATOR (Sandbox)', 'value': 'sim'},
                        {'label': '📡 BACKTEST (Generator)', 'value': 'algo'}
                    ],
                    value='rh', style={'fontFamily': 'monospace'}
                )
            ], width=4)
        ], className="mb-4 py-3 border-bottom border-secondary"),
        
        dbc.Row([
            dbc.Col([html.Div(id='leak-stats-cards')], width=12, className="mb-4")
        ]),

        dbc.Row([
            dbc.Col([
                html.Div([dcc.Graph(id='leak-bar-chart', config={'displayModeBar': False})], style=PANEL_STYLE)
            ], width=12, className="mb-4")
        ]),
        
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H5("FORENSIC LEDGER (4-Hour Lookahead)", style={"color": COLORS["text_primary"], "marginBottom": "1rem"}),
                    html.Div(id='leak-table-container')
                ], style=PANEL_STYLE)
            ], width=12)
        ])
    ], style=LAYOUT_STYLE)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    [Output('leak-bar-chart', 'figure'), Output('leak-table-container', 'children'), Output('leak-stats-cards', 'children')],
    [Input('leak-source-select', 'value')]
)
def update_leak_monitor(source):
    df = fetch_unified_leak_data(source)
    if df.empty:
        return go.Figure().update_layout(template="plotly_dark", title="NO DATA"), html.Div("No trades found.", className="text-muted"), html.Div()

    # 1. SIDE-BY-SIDE BAR CHART (Easy to Read)
    fig = go.Figure()
    
    actual_colors = [COLORS["accent_success"] if val >= 0 else COLORS["accent_danger"] for val in df['realized_pnl']]
    
    fig.add_trace(go.Bar(
        x=df['time_str'], y=df['realized_pnl'],
        name='Actual PnL', marker_color=actual_colors,
        text=df['realized_pnl'], textposition='outside'
    ))
    
    fig.add_trace(go.Bar(
        x=df['time_str'], y=df['missed_profit'],
        name='Missed Trend Potential', marker_color=COLORS["missed_alpha"], opacity=0.8,
        text=df['missed_profit'], textposition='outside'
    ))
    
    fig.update_layout(
        barmode='group', template="plotly_dark",
        title="Comparison: Realized vs. Left on Table ($)",
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="monospace"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    # 2. SIMPLIFIED TABLE
    table = dash_table.DataTable(
        data=df.to_dict('records'),
        columns=[
            {"name": "ENTRY TIME", "id": "time_str"},
            {"name": "INDEX MOVE (4H)", "id": "index_move"},
            {"name": "ACTUAL PnL ($)", "id": "realized_pnl"},
            {"name": "MISSED ALPHA ($)", "id": "missed_profit"}
        ],
        style_header={'backgroundColor': COLORS["background"], 'color': COLORS["text_primary"], 'fontWeight': 'bold', 'border': 'none', 'borderBottom': '2px solid #334155'},
        style_cell={'backgroundColor': COLORS["panel"], 'color': COLORS["text_secondary"], 'textAlign': 'left', 'padding': '12px', 'border': '1px solid #334155'},
        style_data_conditional=[
            {'if': {'column_id': 'realized_pnl', 'filter_query': '{realized_pnl} < 0'}, 'color': COLORS["accent_danger"], 'fontWeight': 'bold'},
            {'if': {'column_id': 'realized_pnl', 'filter_query': '{realized_pnl} >= 0'}, 'color': COLORS["accent_success"], 'fontWeight': 'bold'},
            {'if': {'column_id': 'missed_profit'}, 'color': COLORS["missed_alpha"], 'fontWeight': 'bold'}
        ]
    )

    # 3. TOP SUMMARY CARDS
    total_trades = len(df)
    avg_missed = df['missed_profit'].mean()
    
    cards = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("TRADES ANALYZED", className="text-muted mb-1"), html.H3(f"{total_trades}", className="text-info m-0")])], color="dark", inverse=True, outline=True), width=4),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("AVG MISSED ALPHA (PER TRADE)", className="text-muted mb-1"), html.H3(f"${avg_missed:,.2f}", style={"color": COLORS["missed_alpha"]}, className="m-0")])], color="dark", inverse=True, outline=True), width=4),
    ])

    return fig, table, cards