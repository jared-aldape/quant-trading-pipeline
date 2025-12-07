import dash
from dash import dash_table, html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
import pandas as pd
import duckdb
from src.utils import config

# ==============================================================================
# 1. DATA CONTROLLER (Transactional)
# ==============================================================================
def fetch_ledger():
    """Fetches the transactional history (Buy & Sell rows)."""
    if not config.DB_FILE.exists(): return pd.DataFrame()
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # Check if new table exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_LIVE_LOG not in tables:
            con.close()
            return pd.DataFrame()

        # Fetch Transactional Columns
        # Schema: trans_id, timestamp, ticker, action, qty, price, fees, amount, balance_snapshot...
        query = f"""
            SELECT 
                timestamp, 
                ticker, 
                action, 
                qty, 
                price, 
                fees, 
                amount, 
                balance_snapshot 
            FROM {config.TBL_LIVE_LOG} 
            ORDER BY timestamp DESC
        """
        df = con.execute(query).df()
        con.close()
        
        # Format for Display
        if not df.empty:
            df['timestamp'] = df['timestamp'].astype(str)
            
        return df
    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 2. LAYOUT (Robinhood Style)
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("TRANSACTION HISTORY", className="display-6 fw-bold text-white"),
                html.P("Ledger of all debits (Buys) and credits (Sells).", className="text-muted lead")
            ], width=8),
            dbc.Col([
                dbc.Button("↻ REFRESH", id='ledger-refresh-btn', color="info", outline=True, className="float-end mt-2")
            ], width=4)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ACCOUNT ACTIVITY", className="fw-bold", style={'backgroundColor': '#1E222D', 'color': '#00d2ff'}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='ledger-table',
                            columns=[
                                {'name': 'Date', 'id': 'timestamp'},
                                {'name': 'Ticker', 'id': 'ticker'},
                                {'name': 'Action', 'id': 'action'},
                                {'name': 'Price', 'id': 'price', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                                {'name': 'Fees', 'id': 'fees', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                                {'name': 'Amount', 'id': 'amount', 'type': 'numeric', 'format': {'specifier': '+$.2f'}}, # Shows +/- sign
                                {'name': 'Balance', 'id': 'balance_snapshot', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                            ],
                            data=[],
                            style_header={'backgroundColor': '#1E222D', 'color': 'white', 'fontWeight': 'bold', 'border': '1px solid #444'},
                            style_cell={'backgroundColor': '#0B0C10', 'color': '#EEE', 'border': '1px solid #333', 'fontFamily': 'monospace', 'textAlign': 'left'},
                            
                            # Conditional Formatting (Green for Credits, Red/White for Debits)
                            style_data_conditional=[
                                {
                                    'if': {'filter_query': '{amount} > 0', 'column_id': 'amount'},
                                    'color': '#00ff41', 'fontWeight': 'bold'
                                },
                                {
                                    'if': {'filter_query': '{amount} < 0', 'column_id': 'amount'},
                                    'color': '#ffffff' # White for cost/debit
                                },
                                {
                                    'if': {'filter_query': '{action} = "BUY"', 'column_id': 'action'},
                                    'color': '#00d2ff' # Blue for Buy
                                },
                                {
                                    'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'},
                                    'color': '#f39c12' # Orange for Sell
                                },
                            ],
                            page_size=20,
                            style_table={'overflowX': 'auto'}
                        )
                    ], style={'backgroundColor': '#000000'})
                ], className="shadow mb-3")
            ], width=12)
        ]),
        
        # Auto-refresh every 5s to catch new trades
        dcc.Interval(id='ledger-interval', interval=5000, n_intervals=0)

    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    Output('ledger-table', 'data'),
    [Input('ledger-interval', 'n_intervals'),
     Input('ledger-refresh-btn', 'n_clicks')]
)
def update_ledger_table(n, click):
    df = fetch_ledger()
    return df.to_dict('records')