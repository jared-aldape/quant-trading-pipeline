# **🚀 Quant OS v2.3: The Fractal Engine**

**"UTC in the Vault, Local on the Glass. Flow in the Math."**

This document outlines the architecture, protocols, and usage of the **Quant OS v2.3** financial operating system. This version retires the RSI Mean-Reversion logic in favor of the **Fractal Flow Strategy**, introduces **XSP Scaling Standards**, and streamlines the live workflow into a pure monitoring system.

## **🏛️ The Five Laws (v2.3 Amendments)**

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
   * **Protocol:** T-1 Enforcement prevents API errors by strictly rejecting "Same Day" option requests.  
2. **⚖️ The Scaling Law (NEW):**  
   * **Reality:** We trade **XSP** (Mini-SPX).  
   * **Normalization:** All SPX (^GSPC) and Futures (/ES) data is mathematically divided by 10 in the visualization layer.  
   * **Result:** Charts, Strikes, and P\&L align perfectly on the $600 scale, preventing "Out of the Money" graph errors.  
3. **🛡️** The Integrity **Law:**  
   * **Golden Source:** market\_data/quant\_strategy.duckdb is the single source of truth.  
   * **Persistence:** Tools do not pass CSV files. The Pipeline writes to the DB; Tools read from the DB.  
4. **👁️ The Observability Law:**  
   * **No Silent Failures:** Every script logs forensic details to the console.  
   * **Visual Validation:** The Analysis Dashboard explicitly marks the *exact entry minute* with a vertical line to verify signal alignment.  
5. **🌊 The Flow Law (NEW):**  
   * **Context First:** No trade is valid unless the Macro (1H) and Micro (5m) momentum align.  
   * **RTH Only:** The automated scanner filters out pre-market drift (04:00 AM) to ensure executable RTH entries (06:30 AM PST \- 13:00 PST).

## **🧠 Strategy Protocol: "Fractal Flow"**

The Logic: "The River and the Ripple"  
We only enter when the Micro momentum aligns with the Macro current.

* **Macro (The River):** 1-Hour VIX MACD Histogram.  
  * *Condition:* Must be **Negative** (Red Bars \= Bearish Volatility \= Bullish Market).  
* **Micro (The Ripple):** 5-Minute VIX MACD Line.  
  * *Trigger:* Yellow Line crosses **BELOW** Cyan Signal Line.  
* **The Signal:** **VIX\_FRACTAL\_LONG** (Bullish SPX Entry).

**Scanner Configuration:**

* **File:** src/pipeline/scan\_signals.py  
* **Engine:** Dual-Timeframe (Resamples 5m data to 1H on the fly).  
* **Filter:** Regular Trading Hours (09:30 \- 16:00 ET).

## **🛠️ The Tool Suite**

### **1\. Pipeline: The Morning Routine**

Run this daily to synchronize the Vault.

python src/pipeline/00\_daily\_update.py

* **Ingest:** Indices (SPX, VIX, IRX) & Futures (/ES).  
* **Scan:** Runs the **Fractal Flow Engine** to rebuild the trade\_manifest.  
* **Options:** Fetches XSP option chains for identified signal days.

### **2\. Live Dashboard: The Optical Scope**

* **Role:** High-Speed Execution Monitor.  
* **Status:** "Pure Monitor" (No database writing/journaling features).  
* **Visual Stack:**  
  * **Row 1:** Market Context (XSP vs /ES Futures overlay).  
  * **Row 2:** **Fractal Flow Engine** (1H Background Bars vs 5m Crossover Lines).  
  * **Row 3:** VIX RSI (Overextension check).  
* **Access:** python 14\_live\_dashboard.py

### **3\. Analysis Dashboard: The Forensic Lab**

* **Role:** Post-Game Review & Verification.  
* **Features:**  
  * **Signal Replay:** Dropdown list of every VIX\_FRACTAL\_LONG event found by the scanner.  
  * **Visual Proof:** A **Vertical Blue Dashed Line** marks the exact moment of entry on the VIX chart to verify the crossover.  
  * **Scaled P\&L:** Overlays the XSP Option P\&L curve directly onto the Scaled Spot Price candles.  
* **Access:** python 08\_dashboard.py

## **🔧 Database Schema**

| Table Name | Content | Update Frequency |
| :---- | :---- | :---- |
| indices\_1m | SPX, VIX, IRX OHLCV (UTC) | Daily |
| futures\_1m | /ES Futures (UTC) | Daily |
| options\_1m | XSP Options (UTC) | T-1 (Daily) |
| trade\_manifest | Valid Fractal Signals (Type, Price, Meta) | On Scan |

## **🚀 Operational Workflow**

1. **Ingest & Scan:**  
   python src/pipeline/00\_daily\_update.py

2. **Live Monitoring (06:30 AM PST):**  
   python 14\_live\_dashboard.py

   * *Watch Row 2:* Wait for Yellow line to cross Cyan line while Background is Red.  
3. **Review (Post-Close):**  
   python 08\_dashboard.py  
