import sys
from pathlib import Path

# ==============================================================================
# ARCHITECTURAL MAP (v4.0)
# ==============================================================================
# This map defines the "Intended" data flow of the Quant OS.
# Use this to verify if the actual code matches the design.

DATA_FLOW = {
    "indices_1m (The Truth)": {
        "description": "1-Minute OHLCV data for XSP, SPX, VIX.",
        "writers": [
            "src/data/ingest_indices.py (Primary Ingest)",
            "src/ops/main_pipeline.py (Orchestrator)"
        ],
        "readers": [
            "src/core/engine_scanner.py (Fractal Detection)",
            "src/core/engine_backtest.py (Simulation)",
            "src/interface/view_live_scope.py (Real-Time Chart)",
            "src/interface/view_chart_analysis.py (Forensics)",
            "src/interface/view_replay_analysis.py (VCR)"
        ]
    },
    
    "options_1m (The Chain)": {
        "description": "1-Minute OHLCV for specific Option Contracts.",
        "writers": [
            "src/data/ingest_options_daily.py (Surgical Harvest)",
            "src/core/engine_greeks.py (Updates Delta/Gamma)"
        ],
        "readers": [
            "src/core/engine_backtest.py (Pricing)",
            "src/interface/view_options_sim.py (Trading)",
            "src/interface/view_optimal_lab.py (Ground Truth)"
        ]
    },
    
    "active_rh_log (Reality)": {
        "description": "Raw execution logs from Robinhood (Live Trading).",
        "writers": [
            "src/data/ingest_daily_update.py (CSV Import)",
            "robin_client.py (Future Automation)"
        ],
        "readers": [
            "src/core/engine_forensics.py (FIFO Reconciliation)",
            "src/interface/view_rh_ledger.py (Table View)",
            "src/interface/view_rh_mirror.py (Chart Overlay)"
        ]
    },
    
    "active_simulation_log (The Sandbox)": {
        "description": "Paper trades, Backtests, and Manual Sim results.",
        "writers": [
            "src/core/engine_simulator.py (Manual Entry)",
            "src/core/engine_backtest.py (Auto-Backtest)",
            "src/data/ingest_daily_update.py (Historical Merge)"
        ],
        "readers": [
            "src/interface/view_statistics.py (Win Rate/PnL)",
            "src/interface/view_audit.py (Behavioral Analysis)",
            "src/interface/view_capital_growth.py (Projections)"
        ]
    },
    
    "trade_manifest (The Signals)": {
        "description": "Registry of all algo-generated signals (Fractals).",
        "writers": [
            "src/core/engine_scanner.py (The Brain)",
            "src/core/engine_macro_scanner.py (Macro Filters)"
        ],
        "readers": [
            "src/core/engine_backtest.py (Execution)",
            "src/interface/view_chart_analysis.py (Visual Verification)"
        ]
    },
    
    "optimal_training_manifest (The Gold Standard)": {
        "description": "Human-verified 'Perfect Trades' for ML Training.",
        "writers": [
            "src/interface/view_optimal_lab.py (Manual Commit)",
            "src/data/manage_training_ledger.py (Save Logic)"
        ],
        "readers": [
            "src/core/engine_ml_precision.py (Model Training)"
        ]
    },
    
    "signal_history_log (Deprecated?)": {
        "description": "⚠️ FOUND EMPTY IN AUDIT. Likely an old table name.",
        "writers": ["UNKNOWN - Code may be writing to 'trade_manifest' instead."],
        "readers": ["src/core/engine_ml.py (Legacy)"]
    }
}

def print_map():
    print("\n🗺️  QUANT OS DATA FLOW ARCHITECTURE")
    print("="*80)
    
    for table, flow in DATA_FLOW.items():
        print(f"\n📂 TABLE: {table}")
        print(f"   📝 {flow['description']}")
        
        print("   ⬇️  WRITERS (Input):")
        for w in flow['writers']:
            print(f"      - {w}")
            
        print("   ⬆️  READERS (Output):")
        for r in flow['readers']:
            print(f"      - {r}")
            
    print("\n" + "="*80)
    print("⚠️  ARCHITECT'S NOTE:")
    print("    The Audit revealed 'signal_history_log' is empty while 'trade_manifest' is stale.")
    print("    Recommended Action: Force-Run 'src/core/engine_scanner.py' to jumpstart signal generation.")
    print("="*80 + "\n")

if __name__ == "__main__":
    print_map()