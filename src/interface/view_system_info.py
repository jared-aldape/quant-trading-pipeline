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
import subprocess
from datetime import datetime, date, timedelta

# ==============================================================================
# 0. CONFIG & SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config
from src.core import engine_simulator

# ⚡ UPDATED: 2026 MARKET CALENDAR
MARKET_EVENTS = [
    {"date": "2026-01-01", "event": "New Year's Day", "status": "CLOSED"},
    {"date": "2026-01-19", "event": "MLK Jr. Day", "status": "CLOSED"},
    {"date": "2026-02-16", "event": "Presidents Day", "status": "CLOSED"},
    {"date": "2026-04-03", "event": "Good Friday", "status": "CLOSED"},
    {"date": "2026-05-25", "event": "Memorial Day", "status": "CLOSED"},
    {"date": "2026-06-19", "event": "Juneteenth", "status": "CLOSED"},
    {"date": "2026-07-03", "event": "Independence Day (Obs)", "status": "CLOSED"},
    {"date": "2026-09-07", "event": "Labor Day", "status": "CLOSED"},
    {"date": "2026-11-26", "event": "Thanksgiving", "status": "CLOSED"},
    {"date": "2026-11-27", "event": "Black Friday", "status": "13:00 CLOSE"},
    {"date": "2026-12-24", "event": "Christmas Eve", "status": "13:00 CLOSE"},
    {"date": "2026-12-25", "event": "Christmas Day", "status": "CLOSED"}
]

# ==============================================================================
# 1. HELPERS
# ==============================================================================
def get_db_stats():
    """Returns file size, row counts, and last updated time."""
    if not config.DB_FILE.exists():
        return "N/A", 0, 0, "NEVER"
    
    try:
        size_mb = config.DB_FILE.stat().st_size / (1024 * 1024)
        size_str = f"{size_mb:.2f} MB"
        
        # Track the exact moment the DB was last written to
        last_modified = datetime.fromtimestamp(config.DB_FILE.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        # ⚡ FIX: Read Only to prevent locks
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        
        # Flexible attribute fetching for tables
        opt_table = getattr(config, 'TBL_OPTIONS', 'options_1m')
        sig_table = getattr(config, 'TBL_MANIFEST', 'trade_manifest')
        
        t_opts = con.execute(f"SELECT COUNT(*) FROM {opt_table}").fetchone()[0] if opt_table in tables else 0
        t_sigs = con.execute(f"SELECT COUNT(*) FROM {sig_table}").fetchone()[0] if sig_table in tables else 0
        con.close()
    except Exception as e:
        size_str, t_opts, t_sigs, last_modified = "ERR", 0, 0, "ERROR"
        
    return size_str, t_opts, t_sigs, last_modified

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
    """Reads the last 15 lines of the system log with encoding protection."""
    log_path = ROOT_DIR / "logs" / "system.log"
    
    if not log_path.exists(): return "LOG STATUS: FILE NOT CREATED"
    if log_path.stat().st_size == 0: return "LOG STATUS: SYSTEM STANDBY (NO DATA)"
    
    try:
        # ⚡ FIX: errors='replace' prevents crashes on corrupt bytes
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            if not lines: return "LOG STATUS: EMPTY"
            tail = "".join(lines[-15:])
            return f"--- LIVE LOG STREAM ---\n{tail}"
    except PermissionError:
        return "LOG ERROR: FILE LOCKED"
    except Exception as e:
        return f"LOG ERROR: {str(e)}"

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    # Robust Readme Loader
    readme_content = "README not found."
    for name in ["README.md", "readme.md", "README.txt"]:
        p = ROOT_DIR / name
        if p.exists():
            try: readme_content = p.read_text(encoding='utf-8')
            except: pass
            break

    return dbc.Container([
        
        # --- HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("SYSTEM STATUS MONITOR", className="fw-bold text-white mb-0"),
                html.P("ENGINEERING DECK | DATABASE DIAGNOSTICS | LOGS", className="text-muted small fw-bold mb-0")
            ], width=7),
            dbc.Col([
                html.Div("OPERATIONAL STATUS: NOMINAL", className="text-end text-success font-monospace fw-bold"),
                html.Div(id="sys-last-updated", className="text-end text-muted font-monospace small mb-2"),
                dbc.Button("🔄 REFRESH DATA (PIPELINE)", id="sys-btn-refresh", color="info", size="sm", className="float-end font-monospace fw-bold")
            ], width=5, className="align-self-center text-end")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        dbc.Row([
            # --- COL 1: DATABASE HEALTH ---
            dbc.Col([
                html.H5("DATA CORE METRICS", className="text-info font-monospace mb-3 small fw-bold"),
                
                # DB Stats Card
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Div("DB SIZE", className="small text-muted fw-bold"), html.H4(id="sys-db-size", className="text-white font-monospace")], width=6),
                            dbc.Col([html.Div("LATENCY", className="small text-muted fw-bold"), html.H4(id="sys-ping", className="text-warning font-monospace")], width=6),
                        ], className="mb-3"),
                        
                        html.Div("DISK USAGE", className="small text-muted fw-bold mb-1"),
                        dbc.Progress(id="sys-disk-bar", value=50, color="info", className="mb-3", style={"height": "6px"}),
                        
                        dbc.Row([
                            dbc.Col([html.Small("OPTION ROWS", className="text-muted"), html.Div(id="sys-rows-opt", className="fw-bold font-monospace text-white")], width=6),
                            dbc.Col([html.Small("SIGNAL LOGS", className="text-muted"), html.Div(id="sys-rows-sig", className="fw-bold font-monospace text-white")], width=6),
                        ])
                    ])
                ], className="mb-3 shadow-sm border-secondary", style={"backgroundColor": "#0f172a"}),

                # DANGER ZONE
                dbc.Card([
                    dbc.CardHeader("DANGER ZONE", className="text-danger fw-bold font-monospace small", style={"backgroundColor": "#1a0505"}),
                    dbc.CardBody([
                        html.P("Factory Reset Simulator Data (Irreversible)", className="small text-muted mb-2 font-monospace"),
                        dbc.Button("⚠️ RESET SIMULATION DATA", id="sys-btn-reset", color="danger", outline=True, size="sm", className="w-100 font-monospace fw-bold")
                    ], style={"backgroundColor": "#0f172a"})
                ], className="mb-3 shadow-sm border-danger"),
                
                # System Log Tail
                dbc.Card([
                    dbc.CardHeader("SYSTEM LOG OUTPUT", className="font-monospace small text-muted fw-bold", style={"backgroundColor": "#1e293b"}),
                    dbc.CardBody(
                        html.Pre(id="sys-log-tail", className="text-success small p-2 mb-0 font-monospace", style={"backgroundColor": "#000", "maxHeight": "250px", "overflowY": "auto", "fontSize": "0.75rem", "border": "1px solid #333"})
                    )
                ], className="border-secondary")

            ], width=12, lg=4),

            # --- COL 2: CALENDAR ---
            dbc.Col([
                html.H5("MARKET CALENDAR (2026)", className="text-info font-monospace mb-3 small fw-bold"),
                dbc.Card([
                    dbc.CardBody([
                        dash_table.DataTable(
                            data=MARKET_EVENTS,
                            columns=[
                                {'name': 'DATE', 'id': 'date'},
                                {'name': 'EVENT', 'id': 'event'},
                                {'name': 'STATUS', 'id': 'status'}
                            ],
                            style_header={'backgroundColor': '#1e293b', 'color': '#94a3b8', 'fontWeight': 'bold', 'borderBottom': '1px solid #334155', 'fontFamily': 'monospace'},
                            style_cell={'backgroundColor': '#0f172a', 'color': '#e2e8f0', 'border': 'none', 'borderBottom': '1px solid #1e293b', 'fontFamily': 'monospace', 'fontSize': '13px', 'textAlign': 'left', 'padding': '10px'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{status} contains "CLOSED"'}, 'color': '#ff5555', 'fontWeight': 'bold'},
                                {'if': {'filter_query': '{status} contains "13:00"'}, 'color': '#f59e0b', 'fontWeight': 'bold'},
                            ],
                            page_size=15
                        )
                    ], className="p-0")
                ], className="mb-3 shadow-sm border-secondary")
            ], width=12, lg=4),

            # --- COL 3: MANUAL ---
            dbc.Col([
                html.H5("OPERATIONAL MANUAL", className="text-info font-monospace mb-3 small fw-bold"),
                dbc.Card([
                    dbc.CardBody([
                        dcc.Markdown(
                            readme_content, 
                            className="text-light font-monospace",
                            style={"fontSize": "12px", "lineHeight": "1.6"}
                        )
                    ])
                ], className="mb-3 shadow border-secondary", style={"backgroundColor": "#0f172a", "maxHeight": "80vh", "overflowY": "auto"})
            ], width=12, lg=4)
        ]),
        
        dcc.Interval(id="sys-pulse", interval=5000, n_intervals=0),
        
        # CONFIRMATION MODAL
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("CONFIRM NUCLEAR RESET"), className="text-danger font-monospace fw-bold"),
            dbc.ModalBody(
                html.Div([
                    html.P("You are about to wipe the entire simulation history, including:", className="text-white"),
                    html.Ul([
                        html.Li("All Trade Logs"),
                        html.Li("Portfolio Balance & P&L"),
                        html.Li("Active Positions")
                    ], className="text-warning"),
                    html.P("This action cannot be undone. Are you sure?", className="text-white fw-bold")
                ]), style={"backgroundColor": "#0f172a"}
            ),
            dbc.ModalFooter([
                dbc.Button("ABORT", id="sys-reset-cancel", color="secondary", className="ms-auto font-monospace", n_clicks=0),
                dbc.Button("CONFIRM WIPE", id="sys-reset-confirm", color="danger", className="font-monospace fw-bold", n_clicks=0),
            ], style={"backgroundColor": "#0f172a", "borderTop": "1px solid #333"})
        ], id="sys-reset-modal", is_open=False),
        
        html.Div(id="sys-dummy-out"),
        html.Div(id="sys-dummy-refresh", style={"display": "none"})

    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output("sys-db-size", "children"),
     Output("sys-rows-opt", "children"),
     Output("sys-rows-sig", "children"),
     Output("sys-ping", "children"),
     Output("sys-disk-bar", "value"),
     Output("sys-log-tail", "children"),
     Output("sys-last-updated", "children")],
    [Input("sys-pulse", "n_intervals")]
)
def update_diagnostics(n):
    size, opts, sigs, last_updated = get_db_stats()
    ping = check_latency()
    disk = get_disk_usage()
    log_tail = get_system_log_tail()
    return size, f"{opts:,}", f"{sigs:,}", ping, disk, log_tail, f"LAST DB WRITE: {last_updated}"

@callback(
    [Output("sys-reset-modal", "is_open"), Output("sys-dummy-out", "children")],
    [Input("sys-btn-reset", "n_clicks"), Input("sys-reset-confirm", "n_clicks"), Input("sys-reset-cancel", "n_clicks")],
    [State("sys-reset-modal", "is_open")]
)
def handle_reset(n_req, n_conf, n_canc, is_open):
    trig = ctx.triggered_id
    if trig == "sys-btn-reset": return True, no_update
    if trig == "sys-reset-confirm":
        engine_simulator.reset_session()
        return False, "RESET COMPLETE"
    if trig == "sys-reset-cancel": return False, no_update
    return is_open, no_update

@callback(
    Output("sys-dummy-refresh", "children"),
    Input("sys-btn-refresh", "n_clicks"),
    prevent_initial_call=True
)
def trigger_refresh(n_clicks):
    if n_clicks:
        # Launch the main pipeline script as a non-blocking subprocess
        pipeline_path = ROOT_DIR / "main_pipeline.py"
        subprocess.Popen([sys.executable, str(pipeline_path)])
        return "REFRESH TRIGGERED"
    return no_update