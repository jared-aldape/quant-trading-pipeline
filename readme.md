🏛️ Quant Trading Pipeline (v2.0 Architecture)
"UTC in the Vault, Local on the Glass."
This repository hosts a professional-grade quantitative trading pipeline designed for $\text{VIX/SPX}$ signals and $\text{XSP}$ Option execution. It adheres to strict data integrity and timezone normalization laws, supporting a five-tool ecosystem for validation, forecasting, and training.
________________________________________
📜 The Project Constitution (The Golden Laws)
•	The Timezone Law: ALL timestamps in $\text{DuckDB}$ are stored as UTC. Display conversion to $\text{US/Pacific (PST)}$ happens only at the visualization layer.
•	The Data Integrity Law: Tables enforce strict types and utilize Composite Primary Keys ($\text{datetime\_utc + ticker}$) to prevent data corruption and duplication.
•	The Observability Law: Every script uses centralized logging for audit trails, ensuring no silent failures.
________________________________________
📂 Workflow & Scripts (The Five-Tool Ecosystem)
The system operates on a four-phase data pipeline, which feeds five distinct consumption tools.
Phase	Script File	Function	Output Table(s)
Phase 1: Foundation	$\text{00\_setup\_database.py}$	Initializes the empty, strict Golden Schema.	N/A
Phase 2: Ingestion	$\text{01\_ingest\_indices.py}$	Harvests $\text{SPX, VIX, ES=F}$, and $\text{^IRX}$. Converts all to UTC.	$\text{indices\_1m, futures\_1m, risk\_free\_rate\_daily}$
Phase 3: Processing	$\text{02\_scan\_signals.py}$	Calculates $\text{VIX}$ indicators and detects the $\text{VIX\_MACD\_BEAR\_CROSS}$ signal.	$\text{trade\_manifest}$
	$\text{03\_fetch\_options.py}$	Fetches $\text{XSP}$ Option Chains (ATM $\pm 2$ strikes) from $\text{Polygon.io}$.	$\text{options\_1m}$
	$\text{04\_calc\_greeks.py}$	Calculates $\text{IV, Delta, Gamma, Vega, Theta}$ using Dynamic Interest Rates.	Updates $\text{options\_1m}$
________________________________________
📊 Consumption Tools (The Five Independent Programs)
Each tool is a separate program, enabling a clean executable package for distribution.
ID	Tool Name	Script	Role & Key Feature
1	Historical Backtester	$\text{10\_backtest.py}$	Forensic Validation: Determines actual historical $\text{P\&L}$ and risk metrics (e.g., Hybrid ATR Stop).
2	Trajectory Forecaster	$\text{11\_forecaster\_gui.py}$ (New)	Goal-Oriented Simulation: $\text{GUI}$-driven analysis to chart required $\text{ROI}$ to hit future targets.
3	Analysis Dashboard	$\text{08\_dashboard.py}$	Post-Mortem Review: Visualizes $\text{VIX}$ signals against price action for review (Future: Greek Hovercards).
4	Flight Simulator	$\text{09\_simulator.py}$	Training Environment: Interactive, "fog of war" practice on past data (Future: Click-to-Mark entry).
5	Live Dashboard	$\text{12\_live\_dashboard.py}$ (New)	Operational Awareness: Future state for real-time monitoring and $\text{VIX}$-based status display.
________________________________________
🛠️ Setup Instructions
To ensure a functional environment and prepare for the final packaging, follow this sequence:
1.	Dependencies: Ensure all required libraries are installed from $\text{requirements.txt}$.
2.	Configuration: Add $\text{API}$ Keys and core constants (like the $\text{Section 1256 Tax Rate}$) to $\text{src/utils/config.py}$.
3.	Initialize DB: $\text{python 00\_setup\_database.py}$
4.	Run Pipeline: $\text{python 00\_daily\_update.py}$ (Triggers Steps 1-4)
5.	Launch Tools: $\text{python [Script Name].py}$ (e.g., $\text{python 09\_simulator.py}$)

