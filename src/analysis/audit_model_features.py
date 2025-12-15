import sys
import joblib
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path

# ==============================================================================
# 1. PATH & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("ModelAuditor")

# TARGET THE PRECISION MODEL
MODEL_PATH = config.DATA_DIR / "oracle_v3_precision.joblib"

# ==============================================================================
# 2. AUDIT LOGIC
# ==============================================================================
def audit_brain():
    log.info(f"🧠 OPENING NEURAL ARCHIVE: {MODEL_PATH.name}")
    
    if not MODEL_PATH.exists():
        log.error("❌ Model not found. Run engine_ml_precision.py first.")
        return

    try:
        model = joblib.load(MODEL_PATH)
        
        # Check if it is indeed a RandomForest
        if not hasattr(model, 'feature_importances_'):
            log.error("❌ Model does not support Feature Importance (Not a Tree model).")
            return

        # 3. DEFINE FEATURE NAMES
        # Must match the order in engine_ml_precision.py
        # X = df[['vix_value', 'rsi_value', 'regime_code', 'flow_code', 'hour', 'dow', 'is_call']]
        feature_names = [
            'VIX Value (Volatility)', 
            'RSI (Momentum)', 
            'Market Regime (Trend/Chop)', 
            'Macro Flow (Bull/Bear)', 
            'Hour of Day', 
            'Day of Week', 
            'Call/Put Bias'
        ]
        
        # 4. EXTRACT IMPORTANCE
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1] # Sort descending
        
        print("\n" + "="*60)
        print("🏆 ORACLE FEATURE RANKING (What matters most?)")
        print("="*60)
        
        ranking_data = []
        
        for f in range(len(feature_names)):
            idx = indices[f]
            score = importances[idx] * 100
            name = feature_names[idx]
            print(f"{f+1}. {name:<30} : {score:.2f}%")
            ranking_data.append({'Feature': name, 'Score': score})
            
        print("="*60 + "\n")
        
        # 5. GENERATE VISUAL REPORT (Optional HTML)
        # We can save a quick chart for the user to view if they wish
        df_rank = pd.DataFrame(ranking_data)
        
        fig = go.Figure(go.Bar(
            x=df_rank['Score'],
            y=df_rank['Feature'],
            orientation='h',
            marker=dict(color=df_rank['Score'], colorscale='Viridis')
        ))
        
        fig.update_layout(
            title=f"Oracle v3 Decision Logic (Accuracy: ~75%)",
            xaxis_title="Importance (%)",
            yaxis=dict(autorange="reversed"),
            template="plotly_dark",
            height=500
        )
        
        # Save to data dir for quick check
        output_html = config.DATA_DIR / "oracle_v3_analysis.html"
        fig.write_html(str(output_html))
        log.info(f"📊 Visual Report saved to: {output_html}")

    except Exception as e:
        log.error(f"Audit Failed: {e}")

if __name__ == "__main__":
    audit_brain()