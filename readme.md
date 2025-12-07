**\# ⚔️ QUANT OS v3.3: THE TACTICAL COMMAND SYSTEM**

"Hybrid Truth in the Vault. Surgical Precision on the Glass. Vigilance in the Void."

 Version: v3.3.2 (Distributed Command Build)  
 Status: LIVE / BATTLE READY  
 Node: Quant-OS-Node-1 (AWS US-East-2)  
 Last Update: December 07, 2025

\---

\#\# I. THE PRIME DIRECTIVE

Quant OS is not just a backtester; it is a Tactical Command System designed to eliminate emotional bias through strict algorithmic enforcement. It operates on a Hybrid Architecture:

1\.  Truth (The Vault): Polygon.io (Historical) & DuckDB (Storage).  
2\.  Speed (The Glass): Yahoo Finance (Real-time) & Dash (Visualization).  
3\.  Vigilance (The Sentinel): Python Daemon (Automation).

\---

\#\# II. THE SIX LAWS OF QUANT OS (CORE PROTOCOL)

These laws are non-negotiable. Breaking them corrupts the data and invalidates the strategy.

1\.  🕰️ The Timezone Law:  
     Vault: All database timestamps are Naive UTC.  
     Glass: All visualizations convert strictly to Local Time (PST).  
     Rationale: Preventing "look-ahead bias" caused by timezone shifts.  
2\.  ⚖️ The Scaling Law:  
     Reality: We trade XSP (Mini-SPX) for tax efficiency (60/40 rule).  
     Alignment: Pricing Engine prioritizes ^XSP, uses SPY as proxy fallback.  
3\.  🛡️ The Hard Deck Law:  
     Restriction: No executions within 15 minutes of the Opening Bell (09:30 ET).  
     Expiration: 0DTE options strictly expire at 16:00 ET.  
4\.  💰 The Friction Law:  
     Ghost Fill: Live Simulation applies VIX-Weighted Slippage (High Vol \= Worse Fills).  
     Cost: Deducts Broker Fees ($0.35-$0.50) \+ Regulatory Fees ($0.04) per contract.  
5\.  🧠 The Gatekeeper Law:  
     Filter: Entries require Fractal Flow (VIX Macro/Micro alignment) \+ RSI Momentum.  
6\.  🌊 The Flow Law:  
     Bias: Position sizing is weighted by the 20-Day Macro Flow Bias (Bull/Bear).

\---

\#\# III. DISTRIBUTED COMMAND ARCHITECTURE (v3.3.2)

The monolithic dashboard has been decommissioned in favor of specialized tactical views.

| Route | Interface Name | Purpose |  
| :--- | :--- | :--- |  
| /scope | LIVE MARKET | Situational Awareness. Full-screen chart with ORB, LinReg (Project Delta), and VIX Fractal overlays. |  
| /simulator | OPTION SIMULATOR | Execution Deck. High-speed order entry, Active Positions, and integrated Transactional Ledger. |  
| /mobile | MOBILE COMMAND | Remote Vigilance. High-contrast, vertical interface for monitoring P\&L and "Panic Closing" positions on the go. |  
| /stats | FORENSICS LAB | Deep Audit. Post-combat analysis of both Historical Simulations and the Live Ledger. |

\#\#\# Directory Structure  
\`\`\`text  
QUANT-OS/  
├── data/                 \<-- The Vault (DuckDB) & Backups  
├── assets/               \<-- Visual Protocols (Magitek CSS/SVG)  
├── logs/                 \<-- System Logs  
├── ops/                  \<-- Maintenance Scripts (Backup, Restore, Repair)  
├── src/  
│   ├── core/             \<-- Logic Engines  
│   │   ├── engine\_simulator.py  \<-- Execution Core (Transactional Logic)  
│   │   ├── engine\_ml.py         \<-- The Oracle (Walk-Forward Optimization)  
│   │   ├── engine\_greeks.py     \<-- Gamma Gravity Calculation  
│   │   └── ...  
│   ├── interface/        \<-- The Distributed Glass  
│   │   ├── view\_scope.py        \<-- Live Market  
│   │   ├── view\_order\_deck.py   \<-- Option Simulator  
│   │   ├── view\_mobile.py       \<-- Mobile Command  
│   │   └── ...  
│   └── utils/            \<-- Config & Logging  
├── app.py                \<-- Main Router (Port 8050\)  
└── main\_pipeline.py      \<-- Daily Data Cron Job

---

## **IV. OPERATIONAL WORKFLOW**

### **1\. The Morning Ritual (06:15 PST)**

* **Action:** Run `python ops/backup_vault.py` to secure yesterday's data.  
* **Action:** Check **System Health** (/health). Verify "DB Latency" \< 24 hours.

### **2\. The Watch (06:30 \- 13:00 PST)**

* **Primary Screen:** **Live Market (/scope)** for signal detection.  
* **Secondary Screen:** **Option Simulator (/simulator)** for execution.  
* **Away from Desk:** **Mobile Command (/mobile)** for monitoring.

### **3\. The Review (Post-Market)**

* **Objective:** Audit performance against the model.  
* **Tool:** **Statistics Lab (/stats)**.  
* **Action:** Select **"🔴 LIVE COMBAT LOG"** to review your manual trade performance against the algo.

---

## **V. STRATEGIC ROADMAP**

### **✅ Priority Alpha: The Transactional Bridge**

* **Objective:** Unify Live Trading with Historical Analysis.  
* **Status:** **DEPLOYED**.  
* **Outcome:** `TBL_LIVE_LOG` (11-column schema) records every Buy/Sell action. `view_stats.py` can now audit live trades.

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

---

## **VI. PROJECT LOG**

* **M20:** The Glass Refactor (Mobile Responsiveness).  
* **M21:** Architecture Consolidation (v3.3).  
* **M22:** Visual Protocol Update (Magitek Theme).  
* **M23:** Simulation Core Patch (Ghost Trade Fix).  
* **M24: Distributed Command Split** – Segregated system into Scope, Simulator, and Mobile interfaces.  
* **M25: Transactional Fidelity** – Implemented "Robinhood-Style" ledger, Watchdog Protocol, and Gamma Gravity upgrades.

