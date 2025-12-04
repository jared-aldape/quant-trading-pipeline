@echo off
title QUANT OS v3.1 // TACTICAL COMMAND CONSOLE
color 0A
cls

echo ========================================================
echo   QUANT OS v3.1: THE TACTICAL COMMAND SYSTEM
echo   "Hybrid Truth in the Vault. Surgical Precision on the Glass."
echo ========================================================
echo.

:: 1. UPDATE THE VAULT (Synchronous)
echo [1/3] INITIALIZING DAILY PIPELINE...
echo       Ingesting Indices, calculating Macro Flow, and updating Options...
python main_pipeline.py

:: Check if pipeline succeeded (optional simple pause if you want to verify)
echo.
echo [STATUS] Pipeline Sequence Complete.
echo.

:: 2. DEPLOY THE SENTINEL (Asynchronous / New Window)
echo [2/3] LAUNCHING SENTINEL DAEMON...
echo       Spawning independent process for 24/7 Market Scanning...
start "QUANT OS // SENTINEL" cmd /k "python src/core/sentinel.py"

:: 3. LAUNCH THE GLASS (Main Thread)
echo [3/3] INITIALIZING DASHBOARD INTERFACE...
echo       Loading Neon Console at http://127.0.0.1:8050...
echo.
python app.py

pause