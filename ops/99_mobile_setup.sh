#!/bin/bash

# ==========================================
# QUANT OS v2.1: MOBILE DEPLOYMENT SCRIPT
# ==========================================

echo "🚀 QUANT OS: Initializing Mobile Environment..."
echo "---------------------------------------------"

# 1. Update Termux Repositories
echo "📦 Step 1/5: Updating System..."
pkg update -y && pkg upgrade -y

# 2. Install Heavy System Dependencies
# We need cmake/clang/ninja to compile DuckDB/Scipy on ARM64 chips
echo "🛠️  Step 2/5: Installing Build Tools (This takes a moment)..."
pkg install python git cmake ninja clang make libopenblas freetype libpng tur-repo -y

# 3. Install Scientific Python Stack
# We install these separately because they are heavy and prone to compilation errors
echo "🧮 Step 3/5: Compiling Math Engine (Numpy/Pandas/Scipy)..."
# Tip: Using MATHLIB="openblas" helps scipy compile on Android
export MATHLIB="openblas"
pip install wheel
pip install numpy pandas scipy

# 4. Install Quant Pipeline Libraries
echo "📉 Step 4/5: Installing Quant OS (Dash/DuckDB/YFinance)..."
pip install dash dash-bootstrap-components yfinance plotly duckdb pytz requests

# 5. Initialize V2.1 Architecture
echo "🏗️  Step 5/5: Initializing Database & Pipeline..."

# Navigate to Project Root (assuming script is run from root or ops/)
# If in ops/, go up one level
if [[ "$PWD" == *"ops" ]]; then
    cd ..
fi

# Run the Setup & Ingest Scripts using NEW PATHS
python src/pipeline/00_setup_database.py <<< "yes"
python src/pipeline/00_daily_update.py

echo "---------------------------------------------"
echo "✅ SETUP COMPLETE!"
echo "---------------------------------------------"
echo "👉 To launch the dashboard, run:"
echo "   python app.py"
echo "---------------------------------------------"