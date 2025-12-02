# **🚀 Quant OS v2.4: The Hybrid Engine**

**"Hybrid Truth in the Vault. Proxy Speed on the Glass."**

This document outlines the architecture, protocols, and usage of the **Quant OS v2.4** financial operating system. This version implements the **Free Hybrid Data Protocol**, effectively securing exchange-grade data for the database while maintaining zero-cost real-time monitoring via proxies.

## **🏛️ The Six Laws (v2.4 Amendments)**

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
   * **Protocol:** T-1 Enforcement prevents API errors by strictly rejecting "Same Day" option requests from Polygon Basic.  
2. **⚖️ The Scaling Law:**  
   * **Reality:** We trade **XSP** (Mini-SPX).  
   * **Normalization:** SPX (^GSPC) is divided by 10\. SPY (ETF) is used 1:1.  
   * **Result:** Charts, Strikes, and P\&L align perfectly on the $600 scale.  
3. **🛡️ The Hybrid Law (NEW):**  
   * **The Vault (Truth):** Nightly ingestion uses **Polygon.io (Basic)** for exchange-grade EOD data. If Polygon blocks a ticker (e.g., VIX), the system seamlessly falls back to yfinance to prevent data gaps.  
   * **The Glass (Speed):** Live monitoring uses yfinance for free intraday data, accepting the 15-minute delay for Indices but gaining speed via Proxies.  
4. **🐇 The Proxy Law (NEW):**  
   * **Futures Dead Zone:** Free Futures data (/ES) is unavailable or severely delayed.  
   * **The Fix:** We watch **SPY (ETF)** as the real-time proxy for market context. It trades sufficiently parallel to XSP to serve as a valid leading indicator.  
5. **⚓ The Hard Deck Law (NEW):**  
   * **Simulation Integrity:** The Backtester is forbidden from executing trades within **15 minutes** of the Opening Bell (09:30 ET).  
   * **Reality Check:** This prevents the engine from "filling" orders at unrealistic prices during the opening spread chaos.  
6. **🌊 The Flow Law:**  
   * **Context First:** No trade is valid unless the Macro (1H) and Micro (5m) momentum align.  
   * **RTH Only:** The automated scanner filters out pre-market drift to ensure executable RTH entries.

## **🧠 Strategy Protocol: "Fractal Flow"**

The Logic: "The River and the Ripple"  
We only enter when the Micro momentum aligns with the Macro current.

* **Macro (The River):** 1-Hour VIX MACD Histogram.  
  * *Condition:* Must be **Negative** (Red Bars \= Bearish Volatility \= Bullish Market).  
* **Micro (The Ripple):** 5-Minute VIX MACD Line.  
  * *Trigger:* Yellow Line crosses **BELOW** Cyan Signal Line.  
* **The Signal:** **VIX\_FRACTAL\_LONG** (Bullish SPX Entry).

## **🛠️ The Tool Suite**

### **1\. Pipeline: The Morning Routine**

Run this daily to synchronize the Vault with Hybrid Truth.

python src/pipeline/00\_daily\_update.py

* **Ingest (Hybrid):** Fetches SPX/VIX/IRX using Polygon EOD. Falls back to Yahoo if blocked.  
* **Scan:** Runs the **Fractal Flow Engine** to rebuild the trade\_manifest.  
* **Options:** Fetches XSP option chains for identified signal days.

### **2\. Live Dashboard: The Command Center**

* **Role:** Real-Time Execution Monitor (Proxy Mode).  
* **Visual Stack:**  
  * **Row 1:** Market Context (XSP Syn vs **SPY Proxy**).  
  * **Row 2:** **Fractal Flow Engine** (1H Background Bars vs 5m Crossover Lines).  
  * **Row 3:** VIX RSI (Overextension check).  
* **Access:**  
  python 14\_live\_dashboard.py

### **3\. Analysis Dashboard: The Forensic Lab**

* **Role:** Post-Game Review & Verification.  
* **Features:**  
  * **Visual Proof:** Vertical line marks the exact entry minute.  
  * **Scaled P\&L:** Overlays the XSP Option P\&L curve directly onto the Scaled Spot Price.  
* **Access:**  
  python 08\_dashboard.py

### **4\. Backtester: The Time Machine**

* **Role:** Strategy Verification.  
* **Features:**  
  * **Hard Deck:** Enforces 15-minute open buffer.  
  * **Tax Engine:** Calculates Section 1256 tax implications (60/40 split).  
* **Access:**  
  python 11\_backtest.py

## **🔧 Database Schema (DuckDB)**

| Table Name | Content | Update Frequency | Source |
| :---- | :---- | :---- | :---- |
| indices\_1m | SPX, VIX, IRX OHLCV | Daily | **Polygon (Primary) / Yahoo (Fallback)** |
| options\_1m | XSP Options (UTC) | T-1 (Daily) | **Polygon** |
| trade\_manifest | Valid Fractal Signals | On Scan | **Internal Engine** |
| active\_simulation\_log | Backtest Results | On Run | **Backtester** |

## **🚀 Operational Workflow**

1. Ingest & Scan (8:00 PM PST):  
   python src/pipeline/00\_daily\_update.py  
   (This repairs the Vault with official Polygon data from the closed session)  
2. Live Monitoring (06:30 AM PST):  
   python 14\_live\_dashboard.py  
   * *Watch Row 2:* Wait for Yellow line to cross Cyan line while Background is Red.  
   * *Context:* Confirm trend with SPY (Orange Line) on Row 1\.  
3. Review (Post-Close):  
   python 08\_dashboard.py