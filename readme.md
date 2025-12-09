# **⚔️ QUANT OS v3.3: THE TACTICAL COMMAND SYSTEM**

**"Hybrid Truth in the Vault. Surgical Precision on the Glass. Vigilance in the Void."**

* **Version:** v3.3.3 (Canvas Integration Build)  
* **Status:** **LIVE / BATTLE READY**  
* **Node:** Quant-OS-Node-1 (AWS US-East-2)  
* **Last Update:** December 09, 2025

## **I. THE PRIME DIRECTIVE**

Quant OS is not just a backtester; it is a **Tactical Command System** designed to eliminate emotional bias through strict algorithmic enforcement. It operates on a **Hybrid Architecture**:

1. **Truth (The Vault):** Polygon.io (Historical) & DuckDB (Storage).  
2. **Speed (The Glass):** Yahoo Finance (Real-time) & Dash (Visualization).  
3. **Vigilance (The Sentinel):** Python Daemon (Automation).

## **II. THE SIX LAWS OF QUANT OS (CORE PROTOCOL)**

*These laws are non-negotiable. Breaking them corrupts the data and invalidates the strategy.*

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
   * *Rationale:* Preventing "look-ahead bias" caused by timezone shifts.  
2. **⚖️ The Scaling Law:**  
   * **Reality:** We trade **XSP** (Mini-SPX) for tax efficiency (60/40 rule).  
   * **Alignment:** Pricing Engine prioritizes **^XSP**, uses **SPY** as proxy only if primary feed fails.  
3. **🛡️ The Persistence Law:**  
   * **Simulation:** Backtests run in RAM (Sandbox).  
   * **Commitment:** Results are only saved to the Vault if the "Commit to Stats Lab" protocol is invoked.  
   * *Rationale:* Prevents pollution of the historical record with experimental runs.  
4. **📉 The Drawdown Law:**  
   * **Circuit Breaker:** If Daily PnL hits **\-5.0%**, the system locks out new entries.  
   * **Recovery:** Trading resumes only after a manual reset or 09:30 AM the next session.  
5. **🧩 The Fractal Law:**  
   * **Macro:** 1-Hour MACD defines the **Bias** (Bull/Bear).  
   * **Micro:** 5-Minute RSI defines the **Entry** (Oversold/Overbought).  
   * *Rationale:* Never trade against the tide.  
6. **🧱 The Separation Law:**  
   * **Backtest:** The Generator (Hypothetical).  
   * **Stats Lab:** The Auditor (Historical).  
   * *Rationale:* **"When the shit goes down, ya better be ready."** The operational record must remain pristine and accessible instantly, uncontaminated by theoretical simulations.

## **V. STRATEGIC ROADMAP**

### **✅ Priority Alpha: The Transactional Bridge**

* **Objective:** Unify Live Trading with Historical Analysis.  
* **Status:** **DEPLOYED**.  
* **Outcome:** TBL\_LIVE\_LOG (11-column schema) records every Buy/Sell action. view\_stats.py can now audit live trades.

### **✅ Priority Bravo: The Oracle (ML)**

* **Objective:** Train Random Forest on historical outcomes.  
* **Status:** **DEPLOYED**.  
* **Outcome:** Walk-Forward Optimization implemented. Probability Score displayed on all Command Screens.

### **✅ Priority Charlie: Resilience Protocols**

* **Objective:** Prevent data loss and UI freezes.  
* **Status:** **DEPLOYED**.  
* **Outcome:**  
  * **Watchdog:** Fallback to Vault prices if API fails.  
  * **Smart Throttling:** Burst-mode ingestion.  
  * **Black Box:** Automated DuckDB backups.

### **⚪ Priority Delta: Multi-User Profiles**

* **Objective:** Separate P\&L/Ledgers for different users.  
* **Status:** Concept Phase.

## **VI. PROJECT LOG**

* **M20:** The Glass Refactor (Mobile Responsiveness).  
* **M21:** Architecture Consolidation (v3.3).  
* **M22:** Visual Protocol Update (Magitek Theme).  
* **M23:** Simulation Core Patch (Ghost Trade Fix).  
* **M24:** Distributed Command Split – Segregated system into Scope, Simulator, and Mobile interfaces.  
* **M25:** Transactional Fidelity – Implemented "Robinhood-Style" ledger.  
* **M26:** Canvas Integration – Integrated Canvas for enhanced visualization and interaction within the Trader Master document.

## **VII. CANVAS INTEGRATION**

**Purpose:** To provide an interactive and visual interface for strategy development, backtesting analysis, and live trading monitoring directly within the Trader Master document.

**Features:**

* **Strategy Canvas:** Drag-and-drop interface for building and modifying trading strategies visually.  
* **Backtest Canvas:** Interactive charts and graphs for analyzing backtest results, including equity curves, drawdowns, and trade distribution.  
* **Live Trading Canvas:** Real-time monitoring of live trading performance, positions, and market data.

**Usage:**

* Access the Canvas interface through the dedicated "Canvas" tab in the Trader Master document.  
* Use the toolbar to select different canvas modes (Strategy, Backtest, Live).  
* Drag and drop elements onto the canvas to customize your view and analysis.

## **VIII. APPENDIX**

*(Technical references, API keys, and legacy notes stored here)*