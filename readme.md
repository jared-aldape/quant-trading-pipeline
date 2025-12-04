# **🚀 Quant OS v3.1: The Tactical Command System**

**"Hybrid Truth in the Vault. Surgical Precision on the Glass."**

Quant OS v3.1 is a professional-grade financial operating system designed to eliminate emotional bias and validate trading profitability using real-world market friction and advanced statistical analysis. It operates on a **Hybrid Architecture**: Polygon.io for historical "Truth" (Vault) and Yahoo Finance for real-time "Speed" (Glass).

## **⚡ SYSTEM STATUS: DEPLOYED (AWS)**

* **Node:** Quant-OS-Node-1 (US-East-2)  
* **Sentinel:** **ARMED** (24/7 Daemon)  
* **Pipeline:** **AUTOMATED** (Daily Cron @ 06:00 PST)  
* **Interface:** **ONLINE** (Port 8050\)

## **🏛️ The Six Laws of Quant OS (Core)**

These laws define the non-negotiable standards of data integrity and trade execution within the system:

1. **🕰️ The Timezone Law:** \* **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
2. **⚖️ The Scaling Law:** \* **Reality:** We trade **XSP** (Mini-SPX).  
   * **Alignment:** SPY (ETF) is used as the high-speed price proxy. Futures (/ES) are scaled (1/10th) to align visually.  
3. **🛡️ The Hard Deck Law:** \* **Safety:** The engine is forbidden from executing trades within **15 minutes** of the Opening Bell (09:30 ET) to prevent unrealistic fills during spread chaos.  
4. **💰 The Friction Law:** \* **Reality:** The engine applies **Slippage ($/Share)** and **Robinhood Regulatory Fees** (XSP/Equity logic) to all fills, revealing the *true* cost and expectancy of the strategy.  
5. **🧠** The Gatekeeper **Law:** \* **Filter:** Entry signals are blocked unless they pass **Trend Filters (SMA)** and **Momentum Filters (RSI)**, ensuring only high-quality, non-counter-trend signals are considered.  
6. **🌊 The Flow Law:** \* **Bias:** Trades are weighted dynamically based on the 20-Day Macro Flow (Bull/Bear Bias).

## **🛠️ The Interface (Chronological Workflow)**

The Quant OS Interface (src/interface) is accessible via the **Dash UI**:

| Timeline | UI Name | Function |
| :---- | :---- | :---- |
| **SYSTEM** | **Health Monitor** | Real-time diagnostics for Disk, DB Latency, and Network heartbeat. Displays this Mission Log. |
| **PRESENT** | **Live** **Trading** | Real-time execution dashboard with cached data throttling (15s) and "Neon Console" visuals. |
| **PAST** | **Backtest Engine** | The verification engine. Runs strategies against the Vault with "Battering Ram" persistence. |
| **PAST** | **Practice Mode** | "Fog of War" historical replay tool. Test your reflexes on past market days candle-by-candle. |
| **PAST** | **Trade Auditor** | Deep-dive forensic microscope. Overlays XSP Price, Futures (/ES), and VIX Indicators for tick-level analysis. |
| **FUTURE** | **Predictive Analysis** | Intraday predictive modeling engine using Volatility (ORB) and Linear Regression channels. |

## **🤖 The Sentinel (Automation Layer)**

The **Sentinel** is a headless daemon (quant-sentinel.service) running silently in the background of the AWS Node.

* **Cycle:** Scans SPY/VIX every 60 seconds.  
* **Logic:** Applies the "Fractal Flow" strategy (VIX Macro/Micro).  
* **Alerts:** Dispatches **Discord Webhooks** immediately upon finding a valid setup.  
* **Control:** Managed via systemctl on the remote server.

## **🏗️ System Architecture (Environment Aware)**

The system uses a smart config.py that auto-detects its environment:

QUANT-OS/

├── data/ \<-- The Vault (DuckDB \+ JSON State)

├── logs/ \<-- System Logs (Cron & App)

├── src/

│ ├── core/ \<-- Logic Engines (Backtest, Sentinel, Greeks)

│ ├── interface/ \<-- Dash Views (Health, Live, Audit)

│ └── utils/ \<-- Config (Auto-detects Local vs. AWS paths)

├── app.py \<-- Main UI Entry Point

└── main\_pipeline.py \<-- Daily Data Cron Job (06:00 PST)

## **🚀 Operational Workflow (Commander's Card)**

**1\.** Morning Check **(06:15 PST):**

* Login: ssh \-i quant-key.pem ubuntu@\<IP\>  
* Verify Pipeline: Check "Health Monitor" for updated data latency.  
* Check Logs: tail \-f logs/cron\_pipeline.log

**2\. The Watch (06:30 PST):**

* Access GUI: http://\<IP\>:8050  
* Keep **Live Trading** open.  
* Wait for **Sentinel** alerts on Discord.

**3\. Deployment (CI/CD):**

* **Local:** Edit code \-\> git commit \-\> git push  
* **Remote:** ssh \-\> cd QUANT-OS \-\> git pull \-\> pkill \-f app.py \-\> nohup python app.py &

## **📜 Project Log: Phase 7-10 (Cloud Injection)**

* **M16: Cloud Injection:** Successfully deployed to AWS t3.micro instance.  
* **M17: Memory Protocol:** Implemented Swap File to stabilize Pandas/DuckDB on low-RAM environment.  
* **M18: Sentinel Daemon:** Converted sentinel.py to a systemd background service for 24/7 uptime.  
* **M19: Environment Awareness:** Patched config.py to support dynamic paths for seamless Local/Cloud development.  
* **M20: The Glass Refactor:** Updated UI for mobile