import requests
import json
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
except ImportError:
    print("❌ Critical: Config not found. Ensure running from root.")
    sys.exit(1)

SENTIMENT_FILE = ROOT_DIR / "data" / "macro_sentiment.json"

# ==============================================================================
# 2. THE FREE TIER SENTINEL
# ==============================================================================
class FreeTierSentinel:
    def __init__(self):
        self.api_key = config.POLYGON_API_KEY
        self.base_url = "https://api.polygon.io"
        self.session = requests.Session()
        
    def _get(self, endpoint, params={}):
        """
        Wrapper for Polygon API calls with rate limit handling.
        """
        params['apiKey'] = self.api_key
        try:
            # FREE TIER THROTTLE: Sleep 1s to ensure we don't burst > 5 req/sec (just in case)
            time.sleep(1.5) 
            url = f"{self.base_url}{endpoint}"
            res = self.session.get(url, params=params, timeout=10)
            
            if res.status_code == 429:
                print("⚠️ Rate Limit Hit (429). Cooling down for 60s...")
                time.sleep(61)
                return self._get(endpoint, params) # Retry once
            
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"⚠️ API Error [{endpoint}]: {e}")
            return {}

    def get_sector_rotation(self):
        """
        Compare Tech (XLK) vs Market (SPY) using Previous Close data.
        Logic: If Tech is dragging the market down, it's a bearish signal.
        """
        # Endpoint: /v2/aggs/ticker/{ticker}/prev (Free Tier Friendly)
        print("   >>> [1/3] Fetching SPY Data...")
        spy_data = self._get("/v2/aggs/ticker/SPY/prev", {"adjusted": "true"})
        
        print("   >>> [2/3] Fetching XLK Data...")
        xlk_data = self._get("/v2/aggs/ticker/XLK/prev", {"adjusted": "true"})
        
        if not spy_data.get('results') or not xlk_data.get('results'):
            return "NEUTRAL", 0.0
            
        # Extract Close & Open (Previous Day)
        spy_c = spy_data['results'][0]['c']
        spy_o = spy_data['results'][0]['o']
        spy_pct = (spy_c - spy_o) / spy_o
        
        xlk_c = xlk_data['results'][0]['c']
        xlk_o = xlk_data['results'][0]['o']
        xlk_pct = (xlk_c - xlk_o) / xlk_o
        
        # Relative Strength (Tech - Market)
        rel_strength = xlk_pct - spy_pct
        
        # Thresholds: +/- 1.5% divergence is significant
        if rel_strength < -0.015: 
            return "BEARISH_ROTATION", rel_strength
        if rel_strength > 0.015: 
            return "BULLISH_ROTATION", rel_strength
            
        return "NEUTRAL", rel_strength

    def scan_headlines(self):
        """
        Scan recent news for Macro Trigger words.
        """
        print("   >>> [3/3] Scanning News Headlines...")
        # Endpoint: /v2/reference/news (Free Tier Friendly)
        payload = {"limit": 10, "order": "desc", "sort": "published_utc"}
        data = self._get("/v2/reference/news", payload)
        
        results = data.get('results', [])
        sentiment_score = 0
        events_found = []
        
        # Keywords map (Simple Sentiment)
        keywords = {
            # Bearish (-2)
            "inflation": -2, "cpi high": -2, "hike": -2, "plummet": -2, "recession": -2, "selloff": -2,
            # Bullish (+2)
            "record high": 2, "rally": 2, "rate cut": 2, "cpi cool": 2, "beat earnings": 2, "soft landing": 2
        }
        
        for art in results:
            text = (art.get('title', '') + " " + art.get('description', '')).lower()
            for word, score in keywords.items():
                if word in text:
                    sentiment_score += score
                    events_found.append(word.upper())
                    
        return sentiment_score, list(set(events_found))

# ==============================================================================
# 3. EXECUTION LOGIC
# ==============================================================================
def update_intelligence():
    print("\n📡 POLYGON FREE-TIER SENTINEL INITIALIZED")
    bot = FreeTierSentinel()
    
    # A. Sector Check (Automated "Vibe Check")
    sec_bias, strength = bot.get_sector_rotation()
    print(f"   📊 Sector Mode: {sec_bias} (Rel Strength: {strength*100:.2f}%)")
    
    # B. News Check (Automated "Narrative Check")
    news_score, news_events = bot.scan_headlines()
    news_summary = ", ".join(news_events) if news_events else "None"
    print(f"   📰 News Sentiment: {news_score} (Triggers: {news_summary})")
    
    # C. Decision Synthesis
    final_bias = "NEUTRAL"
    reason = "Market Balanced"
    
    # Sector Logic (Primary Technical Driver)
    if sec_bias == "BEARISH_ROTATION":
        final_bias = "BEARISH"
        reason = f"Tech Sector Weakness (XLK Lag: {strength*100:.2f}%)"
    elif sec_bias == "BULLISH_ROTATION":
        final_bias = "BULLISH"
        reason = f"Tech Sector Strength (XLK Lead: {strength*100:.2f}%)"
        
    # News Logic (The Override)
    # If news is extremely strong, it overrides sector rotation
    if news_score <= -4:
        final_bias = "BEARISH"
        reason = f"Negative Macro News: {news_summary}"
    elif news_score >= 4:
        final_bias = "BULLISH"
        reason = f"Positive Macro News: {news_summary}"

    # D. Save to Commander's Intent
    packet = {
        "bias": final_bias,
        "event": "FREE_TIER_SCAN",
        "weight": 0.80, # Good confidence
        "reason": reason,
        "active": True,
        "updated_at": str(datetime.now())
    }
    
    # Check for Manual Lock
    if SENTIMENT_FILE.exists():
        try:
            with open(SENTIMENT_FILE, 'r') as f:
                curr = json.load(f)
                if curr.get('manual_lock', False):
                    print(f"🔒 Manual Lock Active. Keeping: {curr['bias']}")
                    return
        except:
            pass # File might be corrupt, overwrite it

    with open(SENTIMENT_FILE, 'w') as f:
        json.dump(packet, f, indent=4)
        
    print(f"✅ INTELLIGENCE UPDATED: {final_bias} | {reason}\n")

if __name__ == "__main__":
    update_intelligence()