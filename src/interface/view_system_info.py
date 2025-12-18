import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, ctx, no_update
import dash_bootstrap_components as dbc
import time
import requests
import duckdb
import shutil
import pandas as pd
from pathlib import Path
import sys
from datetime import datetime, date, timedelta

# ==============================================================================
# 0. CONFIG & SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config
from src.core import engine_simulator

# 2025 Market Calendar
MARKET_EVENTS = [
    {"date": "2025-01-01", "event": "New Year's Day", "status": "CLOSED"},
    {"date": "2025-01-20", "event": "MLK Jr. Day", "status": "CLOSED"},
    {"date": "2025-02-17", "event": "Presidents Day", "status": "CLOSED"},
    {"date": "2025-04-18", "event": "Good Friday", "status": "CLOSED"},
    {"date": "2025-05-26", "event": "Memorial Day", "status": "CLOSED"},
    {"date": "2025-06-19", "event": "Juneteenth", "status": "CLOSED"},
    {"date": "2025-07-03", "event": "Indep. Day (Early)", "status": "13:00 CLOSE"},
    {"date": "2025-07-04", "event": "Independence Day", "status": "CLOSED"},
    {"date": "2025-09-01", "event": "Labor Day", "status": "CLOSED"},
    {"date": "2025-11-27", "event": "Thanksgiving", "status": "CLOSED"},
    {"date": "2025-11-28", "event": "Black Friday (Early)", "status": "13:00 CLOSE"},
    {"date": "2025-12-24", "event": "Christmas Eve (Early)", "status": "13:00 CLOSE"},
    {"date": "2025-12-25", "event": "Christmas Day", "status": "CLOSED"}
]

# ==============================================================================
# 1. HELPERS
# ==============================================================================
def get_db_stats():
    """Returns file size and row counts."""
    if not config.DB_FILE.exists():
        return "N/A", 0, 0
    
    try:
        size_mb = config.DB_FILE.stat().st_size / (1024 * 1024)
        size_str = f"{size_mb:.2f} MB"
        
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        # Check if tables exist before counting
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        
        t_opts = con.execute(f"SELECT COUNT(*) FROM {config.TBL_OPTIONS}").fetchone()[0] if config.TBL_OPTIONS in tables else 0
        t_sigs = con.execute(f"SELECT COUNT(*) FROM {config.TBL_MANIFEST}").fetchone()[0] if config.TBL_MANIFEST in tables else 0
        con.close()
    except Exception as e:
        print(f"DB Stat Error: {e}")
        size_str, t_opts, t_sigs = "ERR", 0, 0
        
    return size_str, t_opts, t_sigs

def get_disk_usage():
    """Returns % of disk used."""
    try:
        total, used, free = shutil.disk_usage("/")
        return (used / total) * 100
    except: return 0

def check_latency():
    """Pings Google DNS for connection check."""
    try:
        start = time.time()
        requests.get("http://8.8.8.8", timeout=1)
        lat = (time.time() - start) * 1000
        return f"{lat:.0f} ms"
    except:
        return "OFFLINE"

def get_system_log_tail():
    """Reads the last 10 lines of the system log with fail-safes."""
    log_path = ROOT_DIR / "logs" / "system.log"
    
    # 1. Check if file exists
    if not log_path.exists(): 
        return "LOG STATUS: FILE NOT CREATED"
    
    # 2. Check if file is empty
    if log_path.stat().st_size == 0:
        return "LOG STATUS: SYSTEM STANDBY (NO DATA)"
    
    try:
        # ⚡ ENCODING & LOCK PROTECTION
        # 'errors=replace' prevents crashes on non-UTF8 characters
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            if not lines:
                return "LOG STATUS: EMPTY"
            
            # Return last 10 lines with a visual header
            tail = "".join(lines[-10:])
            return f"--- LAST 10 ENTRIES ---\n{tail}"
            
    except PermissionError:
        return "LOG ERROR: FILE LOCKED BY ANOTHER PROCESS"
    except Exception as e:
        return f"LOG ERROR: {str(e)}"

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    readme_path = ROOT_DIR / "README.md"
    readme_content = readme_path.read_text(encoding='utf-8') if readme_path.exists() else "README.md not found."
    
    return dbc.Container([
        
        # --- HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("SYSTEM BACKEND", className="magitek-h2"),
                html.P("DATABASE DIAGNOSTICS | CALENDAR | SIMULATOR RESET", className="magitek-note")
            ], width=8),
            dbc.Col([
                html.Div("STATUS: OPTIMAL", className="text-end text-success font-monospace fw-bold"),
                html.Div(id="sys-latency", className="text-end text-muted font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9"}),

        dbc.Row([
            # --- COL 1: DATABASE HEALTH ---
            dbc.Col([
                html.H5("DATA CORE", className="text-secondary font-monospace mb-3 small"),
                
                # DB Stats Card
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Div("DB SIZE", className="small text-muted"), html.H4(id="sys-db-size", className="text-white font-monospace")], width=6),
                            dbc.Col([html.Div("LATENCY", className="small text-muted"), html.H4(id="sys-ping", className="text-info font-monospace")], width=6),
                        ], className="mb-3"),
                        
                        html.Div("DISK USAGE", className="small text-muted mb-1"),
                        dbc.Progress(id="sys-disk-bar", value=50, color="success", className="mb-3", style={"height": "5px"}),
                        
                        dbc.Row([
                            dbc.Col([html.Small("OPTION ROWS"), html.Div(id="sys-rows-opt", className="fw-bold font-monospace")], width=6),
                            dbc.Col([html.Small("SIGNALS"), html.Div(id="sys-rows-sig", className="fw-bold font-monospace")], width=6),
                        ])
                    ])
                ], className="mb-3 shadow-sm bg-dark border-secondary"),

                # DANGER ZONE (Simulator Reset)
                dbc.Card([
                    dbc.CardHeader("DANGER ZONE", className="text-danger fw-bold font-monospace small"),
                    dbc.CardBody([
                        html.P("Reset Simulator Data (Nuclear Option)", className="small text-muted mb-2"),
                        dbc.Button("RESET SIMULATION DECK", id="sys-btn-reset", color="danger", outline=True, size="sm", className="w-100 font-monospace")
                    ])
                ], className="mb-3 shadow-sm border-danger bg-black"),
                
                # System Log Tail
                dbc.Card([
                    dbc.CardHeader("SYSTEM LOG (TAIL)", className="font-monospace small text-muted"),
                    dbc.CardBody(
                        html.Pre(id="sys-log-tail", className="text-success small bg-black p-2", style={"maxHeight": "150px", "overflowY": "auto", "fontSize": "0.7rem"})
                    )
                ], className="border-secondary")

            ], width=12, lg=4),

            # --- COL 2: CALENDAR ---
            dbc.Col([
                html.H5("MARKET CALENDAR (2025)", className="text-secondary font-monospace mb-3 small"),
                dbc.Card([
                    dbc.CardBody([
                        dash_table.DataTable(
                            data=MARKET_EVENTS,
                            columns=[
                                {'name': 'DATE', 'id': 'date'},
                                {'name': 'EVENT', 'id': 'event'},
                                {'name': 'STATUS', 'id': 'status'}
                            ],
                            style_header={'backgroundColor': '#1e1e1e', 'color': '#888', 'fontWeight': 'bold', 'border': 'none', 'fontFamily': 'monospace'},
                            style_cell={'backgroundColor': '#1e1e1e', 'color': '#fff', 'border': 'none', 'fontFamily': 'monospace', 'fontSize': '13px', 'textAlign': 'left'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{status} contains "CLOSED"'}, 'color': '#ff5555'},
                                {'if': {'filter_query': '{status} contains "EARLY"'}, 'color': '#f1c40f'},
                            ],
                            page_size=12
                        )
                    ], className="p-0")
                ], className="mb-3 shadow-sm bg-dark border-secondary")
            ], width=12, lg=4),

            # --- COL 3: README ---
            dbc.Col([
                html.H5("MANUAL", className="text-secondary font-monospace mb-3 small"),
                dbc.Card([
                    dbc.CardBody([
                        dcc.Markdown(
                            readme_content, 
                            className="text-white font-monospace",
                            style={"fontSize": "12px", "lineHeight": "1.4"}
                        )
                    ])
                ], className="mb-3 shadow bg-dark border-secondary", style={"maxHeight": "80vh", "overflowY": "auto"})
            ], width=12, lg=4)
        ]),
        
        dcc.Interval(id="sys-pulse", interval=5000, n_intervals=0),
        
        # CONFIRMATION MODAL
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("CONFIRM SIMULATOR RESET")),
            dbc.ModalBody("Are you sure you want to wipe all simulation history? This cannot be undone.", className="text-white"),
            dbc.ModalFooter([
                dbc.Button("CANCEL", id="sys-reset-cancel", className="ms-auto", n_clicks=0),
                dbc.Button("NUKE IT", id="sys-reset-confirm", color="danger", n_clicks=0),
            ])
        ], id="sys-reset-modal", is_open=False, style={"backgroundColor": "#1a2a4a"}),
        
        html.Div(id="sys-dummy-out")

    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output("sys-db-size", "children"),
     Output("sys-rows-opt", "children"),
     Output("sys-rows-sig", "children"),
     Output("sys-ping", "children"),
     Output("sys-disk-bar", "value"),
     Output("sys-log-tail", "children")],
    [Input("sys-pulse", "n_intervals")]
)
def update_diagnostics(n):
    size, opts, sigs = get_db_stats()
    ping = check_latency()
    disk = get_disk_usage()
    log_tail = get_system_log_tail()
    
    return size, f"{opts:,}", f"{sigs:,}", ping, disk, log_tail

@callback(
    [Output("sys-reset-modal", "is_open"), Output("sys-dummy-out", "children")],
    [Input("sys-btn-reset", "n_clicks"), Input("sys-reset-confirm", "n_clicks"), Input("sys-reset-cancel", "n_clicks")],
    [State("sys-reset-modal", "is_open")]
)
def handle_reset(n_req, n_conf, n_canc, is_open):
    trig = ctx.triggered_id
    
    # Open Modal
    if trig == "sys-btn-reset":
        return True, no_update
    
    # Confirm Action
    if trig == "sys-reset-confirm":
        engine_simulator.reset_session()
        return False, "RESET COMPLETE"
        
    # Cancel Action
    if trig == "sys-reset-cancel":
        return False, no_update
        
    # Initial Load / No Trigger
    return is_open, no_update