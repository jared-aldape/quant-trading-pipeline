# **⚔️ QUANT OS v3.4: MAGITEK COMMAND SYSTEM**

**"Hybrid Truth in the Vault. Surgical Precision on the Glass. Vigilance in the Void."**

* **Version:** v3.4 (Magitek UI / Forensics Update)  
* **Status:** **LIVE / BATTLE READY**  
* **Node:** Quant-OS-Node-1 (Local/AWS Hybrid)  
* **Last Update:** December 14, 2025

## **I. THE PRIME DIRECTIVE**

Quant OS is a **Tactical Command System** designed to eliminate emotional bias through strict algorithmic enforcement and superior data visualization. It operates on a **Hybrid Architecture**:

1. **Truth (The Vault):** Polygon.io (Historical) & DuckDB (Storage).  
2. **Speed (The Glass):** Dash/Plotly (Visualization) via Magitek UI.  
3. **Vigilance (The Sentinel):** Python Daemon (Automation).

## **II. THE SIX LAWS OF QUANT OS (CORE PROTOCOL)**

*Non-negotiable rules for data integrity and execution.*

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC** (Universal Time).  
   * **Glass:** All visualizations convert strictly to **Naive US/Pacific** (Local Time).  
   * *Rationale:* Prevents "look-ahead bias" and "ghost signals" caused by timezone shifts.  
2. **⚖️ The Scaling Law:**  
   * **Reality:** We trade **XSP** (Mini-SPX) for tax efficiency (60/40 rule).  
   * **Context:** **SPY** is the proxy for context. **SPX** is purged to reduce API overhead.  
3. **🛡️ The Hard Deck Law:**  
   * **RTH Only:** No signals generated outside 09:30 \- 16:00 ET.  
   * **Orphan Control:** Trades open at 16:00 ET are force-closed in simulations.  
4. **💰 The Friction Law:**  
   * **Simulation:** $0.03 Reg Fee \+ $1.00 Slippage per contract.  
   * **Reality:** Actual fills from Robinhood ledger.  
5. **📉 The Gatekeeper Law:**  
   * **Filter:** Signals must pass Fractal Trend \+ VIX Regime check.  
   * **Oracle:** ML model (v3 Precision) validates signals against 100k+ historical option outcomes.  
6. **🌊 The Flow Law:**  
   * **Context:** Trades align with 20-Day Macro Flow (Bull/Bear Bias).

## **III. SYSTEM ARCHITECTURE (v3.4)**

### **A. The Core (Logic)**

* quant\_launcher.py: **Central Command.** Replaces app.py. Unified dashboard entry point.  
* engine\_scanner.py: **The Brain.** Scans XSP/VIX for Fractal setups. Purges old signals daily to prevent fragmentation.  
* engine\_backtest.py: **The Simulator.** Deterministic physics engine. Supports "What If" parameters (Ideal Gain, Max Loss, Trailing Stop).  
* engine\_forensics.py: **The Auditor.** FIFO Reconciler that pairs Buy/Sell rows into closed trades for PnL analysis.  
* engine\_ml\_precision.py: **The Oracle.** Random Forest model trained on real option pricing to predict trade success.

### **B. The Data (Ingestion)**

* ingest\_indices.py: Fetches XSP/VIX OHLCV. (SPX removed).  
* ingest\_options\_daily.py: **Surgical Harvester.** Downloads 1-minute bars for ATM \+/- 2 strikes *only*. Uses SPY proxy for targeting.  
* ingest\_ledger.py: Imports Robinhood CSVs into active\_rh\_log.

### **C. The Interface (Magitek UI)**

* **Theme:** Dark Mode (\#283878 Blue / \#fde722 Gold). Monospace Fonts (VT323).  
* view\_live\_scope.py: **ATB SCOPE.** Live HUD with VIX Thermometer, Dead Air warning, and Extension alerts.  
* view\_replay\_analysis.py: **CHRONICLE COMMAND.** Market Replay with VCR controls (Play/Pause/Speed) and Blind Mode.  
* view\_chart\_analysis.py: **LIBRA SCAN.** Forensic deep-dive. Overlays signals on XSP with VIX Regime tint.  
* view\_options\_sim.py: **TRAINING GROUNDS.** Manual paper trading sandbox.  
* view\_audit.py: **JUDGMENT.** Transaction-level ledger with Heatmaps and Volume analysis.  
* view\_statistics.py: **JOB STATS.** High-level PnL, Win Rate, and Equity Curve.  
* view\_capital\_growth.py: **LEVEL UP.** Geometric growth forecaster with Reality Overlay and Target Seeker.

## **IV. OPERATIONAL WORKFLOW**

### **1\. Morning Protocol (06:00 PST)**

* **Run:** python main\_pipeline.py  
  * *Action:* Updates XSP/VIX data.  
  * *Action:* Harvester downloads missing option chains (Surgical Strike).  
  * *Action:* Scanner generates fresh signals for the day.

### **2\. The Watch (06:30 PST)**

* **Run:** python quant\_launcher.py \-\> Select **ATB SCOPE**.  
* **Monitor:**  
  * **VIX Thermometer:** Is it floored (\<20%)? Caution on Longs.  
  * **ORB Status:** Is the box grey ("Dead Air")? Stand down.  
  * **Oracle Confidence:** Is the AI score \> 65%? Green light.

### **3\. The Review (Post-Market)**

* **Action:** Export Robinhood CSV.  
* **Run:** python src/data/ingest\_ledger.py (Hydrate Ledger).  
* **Launch:** quant\_launcher.py \-\> Select **JUDGMENT** or **JOB STATS**.  
* **Verify:** Did I follow the plan? What was the slippage?

## **V. STRATEGIC ROADMAP**

* ✅ **Priority Alpha:** Unified Launcher & UI Standardization (Completed).  
* ✅ **Priority Bravo:** FIFO Reconciler for Real PnL (Completed).  
* ✅ **Priority Charlie:** Oracle v3 Integration (Completed).  
* ⚪ **Priority Delta:** **Headless Automation.**  
  * *Goal:* Connect engine\_scanner.py directly to robin\_client.py for auto-execution.  
  * *Status:* Logic exists, requires wiring.  
* ⚪ **Priority Echo:** **Multi-Leg Spreads.**  
  * *Goal:* Automate Vertical Spreads to cap risk.  
  * *Status:* Concept phase.

## **VI. PROJECT LOG (Recent)**

* **M24:** **Magitek UI Overhaul.** Total visual conversion to FF6 aesthetic.  
* **M25:** **Launcher Consolidation.** Retired app.py and view\_backtest.py.  
* **M26:** **FIFO Engine.** Built logic to pair independent Buy/Sell transactions into closed trades.  
* **M27:** **Surgical Ingestion.** Replaced bulk download with targeted "ATM \+/- 2" daily harvester.  
* **M28:** **SPX Purge.** Removed SPX dependency in favor of XSP-Native architecture.  
* **M29:** **Temporal Fix.** Solved "Future Data" bug preventing ingestion.