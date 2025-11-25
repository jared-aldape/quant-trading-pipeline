#!/bin/bash

# ==========================================
# QUANT OS: MOBILE DEPLOYMENT SCRIPT
# ==========================================

echo "🚀 QUANT OS: Initializing Mobile Environment..."
echo "---------------------------------------------"

# 1. Update Termux Repositories
echo "📦 Step 1/4: Updating System..."
pkg update -y && pkg upgrade -y

# 2. Install Heavy System Dependencies
# We need cmake/clang/ninja to compile DuckDB and Scipy on ARM64 chips
echo "🛠️  Step 2/4: Installing Build Tools (This takes a moment)..."
pkg install python git cmake ninja clang make libopenblas freetype libpng tur-repo -y

# 3. Install Scientific Python Stack
# We install these separately because they are heavy and prone to compilation errors
echo "🧮 Step 3/4: Compiling Math Engine (Numpy/Pandas/Scipy)..."
# Tip: Using MATHLIB="openblas" helps scipy compile on Android
export MATHLIB="openblas"
pip install wheel
pip install numpy pandas scipy

# 4. Install Quant Pipeline Libraries
echo "📉 Step 4/4: Installing Quant OS (Dash/DuckDB/YFinance)..."
pip install dash dash-bootstrap-components yfinance plotly duckdb pytz requests

# 5. Finalize
echo "---------------------------------------------"
echo "✅ SETUP COMPLETE!"
echo "---------------------------------------------"
echo "👉 To launch the dashboard, run:"
echo "   python app.py"
echo "---------------------------------------------"