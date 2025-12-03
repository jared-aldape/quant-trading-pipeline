# **🚀 Quant OS v3.0: The Tactical Command System**

**"Hybrid Truth in the Vault. Surgical Precision on the Glass."**

Quant OS v3.0 is a professional-grade financial operating system designed to eliminate emotional bias and validate trading profitability using real-world market friction and advanced statistical analysis. It operates on a **Hybrid Architecture**: Polygon.io for historical "Truth" (Vault) and Yahoo Finance for real-time "Speed" (Glass).

## **🏛️ The Six Laws of Quant OS (v3.0 Core)**

These laws define the non-negotiable standards of data integrity and trade execution within the system:

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
2. **⚖️ The Scaling Law:**  
   * **Reality:** We trade **XSP** (Mini-SPX).  
   * **Alignment:** SPY (ETF) is used as the high-speed price proxy. Futures (/ES) are scaled (1/10th) to align visually.  
3. **🛡️ The Hard Deck Law:**  
   * **Safety:** The engine is forbidden from executing trades within **15 minutes** of the Opening Bell (09:30 ET) to prevent unrealistic fills during spread chaos.  
4. **💰 The Friction Law:**  
   * **Reality:** The engine applies **Slippage ($/Share)** and **Robinhood Regulatory Fees** (XSP/Equity logic) to all fills, revealing the *true* cost and expectancy of the strategy.  
5. **🧠 The Gatekeeper Law:**  
   * **Filter:** Entry signals are blocked unless they pass **Trend Filters (SMA)** and **Momentum Filters (RSI)**, ensuring only high-quality, non-counter-trend signals are considered.  
6. **🌊 The Flow Law:**  
   * **Bias:** Trades are weighted dynamically based on the 20-Day Macro Flow (Bull/Bear Bias).

## **🛠️ The Tool Suite (Manual Operations)**

The core of the Quant OS is organized into six powerful, integrated modules accessible via the **Dash UI**:

| Module | UI Name | Function |
| :---- | :---- | :---- |
| **Simulator** | **Live Trading** | Real-time execution dashboard with cached data throttling (15s) and "Neon Console" visuals. |
| **Gym** | **Practice Mode** | "Fog of War" historical replay tool. Test your reflexes on past market days candle-by-candle. |
| **Backtester** | **Historical Test** | The verification engine. Runs strategies against the Vault with "Battering Ram" persistence. |
| **Replay** | **Trade Auditor** | Deep-dive forensic microscope. Overlays XSP Price, Futures (/ES), and VIX Indicators for any past trade. |
| **Forensics** | **Performance Stats** | Statistical audit lab. Visualizes Signal Decay, Hourly Kill Zones, and Theta Risk. |
| **Capital** | **Growth Projection** | Monte Carlo simulation engine. Projects future account growth using your actual "Strategy DNA." |
| **Prophet** | **Intraday Targets** | Predictive modeling engine using Volatility (ORB) and Linear Regression channels. |

## **🤖 The Sentinel (Automation Layer)**

**Phase 4** introduced Headless Automation to move from Reactive to Proactive trading.

* **Daemon:** src/core/sentinel.py  
* **Function:** Runs silently in the background (CLI).  
* **Cycle:** Scans SPY/VIX every 60 seconds.  
* **Logic:** Applies the exact same "Fractal Flow" strategy as the Backtester.  
* **Alerts:** Dispatches **Discord Webhooks** and System Beeps immediately upon finding a valid setup.

## **🏗️ System Architecture**

The system uses a Domain-Driven Design for scalable operation:

QUANT-OS/  
├── data/                   \<-- The Vault (DuckDB \+ JSON State)  
├── logs/                   \<-- System Logs  
├── src/  
│   ├── core/               \<-- The "Brains" (Logic & Engines)  
│   │   ├── engine\_backtest.py      (Simulation & DB Writer)  
│   │   ├── engine\_simulator.py     (Live State & Caching)  
│   │   ├── engine\_scanner.py       (Signal Generation)  
│   │   ├── sentinel.py             (Automation Daemon)  
│   │   └── strat\_fractal.py        (The Strategy Source)  
│   │  
│   ├── interface/          \<-- The "Glass" (Dash UI Views)  
│   │   ├── view\_simulator.py       (Live Trading)  
│   │   ├── view\_backtester.py      (Historical Test)  
│   │   ├── view\_capital.py         (Growth Projection)  
│   │   └── view\_signal\_replay.py   (Trade Auditor)  
│   │  
│   └── data/               \<-- The Ingestors  
│       ├── ingest\_indices.py       (SPX, VIX, Futures)  
│       └── ingest\_options.py       (Option Chains)  
│  
├── app.py                  \<-- Main UI Entry Point  
└── main\_pipeline.py        \<-- Daily Data Cron Job

## **🚀 Operational Workflow**

1. **Morning Prep (06:00 PST):**  
   * Run python main\_pipeline.py to ingest yesterday's data and update the "Truth" Vault.  
2. **The Watch (06:30 PST):**  
   * Launch the UI: python app.py.  
   * Launch the Sentinel: python src/core/sentinel.py (in a separate terminal).  
3. **Execution:**  
   * Wait for Sentinel Alert 🚨.  
   * Verify signal in **Live Trading** dashboard.  
   * Execute trade (Buy Call/Put).  
4. **Review (Post-Market):**  
   * Run **Historical Test** to validate the day's strategy.  
   * Check **Performance Stats** to track long-term drift.  
   * Use **Trade Auditor** to dissect any losses.

*v3.0 Finalized \- Ready for Deployment*