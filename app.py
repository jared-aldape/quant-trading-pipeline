import sys
import os
import subprocess
import webbrowser
from threading import Timer
import dash
from dash import Dash, html, dcc, callback, Input, Output

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# Define the Project Root (The folder containing this app.py)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Add Root to System Path (Ensures immediate imports work)
sys.path.append(ROOT_DIR)

# Define the location of the GUI Tools
TOOLS_DIR = os.path.join(ROOT_DIR, "src", "tools")

# ==============================================================================
# 2. GUI LAYOUT (MILITARY TERMINAL AESTHETIC)
# ==============================================================================
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "QUANT OS v2.1"

# High-contrast 'Dark Mode' Styling
app.layout = html.Div(style={
    'backgroundColor': '#111', 
    'color': '#eee', 
    'fontFamily': 'Consolas, "Courier New", monospace', 
    'height': '100vh', 
    'padding': '40px',
    'boxSizing': 'border-box'
}, children=[
    
    # HEADER
    html.H1("QUANT OS v2.1 // COMMAND TERMINAL", style={
        'textAlign': 'center', 
        'color': '#00ff00', 
        'textShadow': '0px 0px 10px #00ff00',
        'marginBottom': '10px'
    }),
    html.Hr(style={'borderColor': '#333', 'marginBottom': '40px'}),
    
    # BUTTON GRID
    html.Div(style={
        'display': 'grid', 
        'gridTemplateColumns': 'repeat(3, 1fr)', 
        'gap': '30px', 
        'maxWidth': '1200px', 
        'margin': '0 auto'
    }, children=[
        
        # ROW 1: STRATEGY & PLANNING
        html.Button("1. BACKTESTER (BLUE)", id='btn-backtest', n_clicks=0, style={
            'padding': '30px', 'fontSize': '18px', 'fontWeight': 'bold',
            'backgroundColor': '#0a0a0a', 'color': 'cyan', 
            'border': '2px solid cyan', 'cursor': 'pointer',
            'boxShadow': '0px 0px 5px cyan'
        }),
        
        html.Button("2. FORECASTER (GREEN)", id='btn-forecast', n_clicks=0, style={
            'padding': '30px', 'fontSize': '18px', 'fontWeight': 'bold',
            'backgroundColor': '#0a0a0a', 'color': 'lime', 
            'border': '2px solid lime', 'cursor': 'pointer',
            'boxShadow': '0px 0px 5px lime'
        }),
        
        html.Button("3. ANALYSIS (CYAN)", id='btn-analysis', n_clicks=0, style={
            'padding': '30px', 'fontSize': '18px', 'fontWeight': 'bold',
            'backgroundColor': '#0a0a0a', 'color': 'cyan', 
            'border': '2px solid cyan', 'cursor': 'pointer',
            'boxShadow': '0px 0px 5px cyan'
        }),
        
        # ROW 2: EXECUTION & OPS
        html.Button("4. SIMULATOR (ORANGE)", id='btn-sim', n_clicks=0, style={
            'padding': '30px', 'fontSize': '18px', 'fontWeight': 'bold',
            'backgroundColor': '#0a0a0a', 'color': 'orange', 
            'border': '2px solid orange', 'cursor': 'pointer',
            'boxShadow': '0px 0px 5px orange'
        }),
        
        html.Button("5. LIVE OPS (RED)", id='btn-live', n_clicks=0, style={
            'padding': '30px', 'fontSize': '18px', 'fontWeight': 'bold',
            'backgroundColor': '#0a0a0a', 'color': 'red', 
            'border': '2px solid red', 'cursor': 'pointer',
            'boxShadow': '0px 0px 5px red'
        }),
        
        html.Button("6. PERISCOPE (TEAL)", id='btn-news', n_clicks=0, style={
            'padding': '30px', 'fontSize': '18px', 'fontWeight': 'bold',
            'backgroundColor': '#0a0a0a', 'color': 'teal', 
            'border': '2px solid teal', 'cursor': 'pointer',
            'boxShadow': '0px 0px 5px teal'
        }),
    ]),
    
    # STATUS OUTPUT AREA
    html.Div(id='output-msg', style={
        'marginTop': '40px', 
        'textAlign': 'center', 
        'color': 'yellow', 
        'fontSize': '16px',
        'borderTop': '1px dashed #444',
        'paddingTop': '20px'
    })
])

# ==============================================================================
# 3. LAUNCH LOGIC (THE BRIDGE TO SRC/TOOLS)
# ==============================================================================
def launch_tool(script_name):
    """
    Launches a script from src/tools/ with the correct environment setup.
    """
    # 1. Construct Full Path
    script_path = os.path.join(TOOLS_DIR, script_name)
    
    # 2. Observability Check
    if not os.path.exists(script_path):
        return f"❌ ERROR: File not found at {script_path}. Check your folder structure."
    
    # 3. Environment Setup (CRITICAL)
    # We copy the current environment and force PYTHONPATH to the Project Root.
    # This allows the tool in src/tools/ to import 'src.utils.config'.
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT_DIR
    
    try:
        # 4. Launch Subprocess
        # We run from ROOT_DIR to preserve relative file access if any
        subprocess.Popen([sys.executable, script_path], cwd=ROOT_DIR, env=env)
        return f"🚀 LAUNCHED: {script_name} (PID: Dispatched)"
    except Exception as e:
        return f"❌ FAILURE: Could not launch {script_name}. Error: {e}"

@callback(Output('output-msg', 'children'),
          [Input('btn-backtest', 'n_clicks'),
           Input('btn-forecast', 'n_clicks'),
           Input('btn-analysis', 'n_clicks'),
           Input('btn-sim', 'n_clicks'),
           Input('btn-live', 'n_clicks'),
           Input('btn-news', 'n_clicks')],
          prevent_initial_call=True)
def handle_click(*args):
    # Identify which button triggered the callback
    ctx = dash.callback_context
    if not ctx.triggered:
        return ""
    
    btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Map Button IDs to Files in src/tools/
    # NOTE: Ensure these files exist in src/tools/
    tool_map = {
        'btn-backtest': '11_backtest.py',     # The Dashboard Controller
        'btn-forecast': '12_forecast.py',
        'btn-analysis': '08_dashboard.py',    # Main Analysis Dash
        'btn-sim':      '09_simulator.py',
        'btn-live':     '14_live_dashboard.py',
        'btn-news':     '13_market_state.py'
    }
    
    target_script = tool_map.get(btn_id)
    if target_script:
        return launch_tool(target_script)
    else:
        return "⚠️ Unknown Tool ID"

# ==============================================================================
# 4. MAIN EXECUTION
# ==============================================================================
if __name__ == '__main__':
    # Auto-open browser after 1 second
    Timer(1, lambda: webbrowser.open("http://127.0.0.1:8050")).start()
    
    # Run Server on Local LAN (Host 0.0.0.0) for Mobile Access
    app.run_server(debug=True, host='0.0.0.0', port=8050)