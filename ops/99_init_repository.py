import os
import subprocess
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# Determine Root: If in 'ops/', go up one level. If in Root, stay here.
CURRENT_DIR = Path(__file__).resolve().parent
if CURRENT_DIR.name == "ops":
    PROJECT_ROOT = CURRENT_DIR.parent
else:
    PROJECT_ROOT = CURRENT_DIR

# The Rules of what to Ignore (The .gitignore)
GITIGNORE_CONTENT = """
# --- Data & Logs (Local Only) ---
market_data/
logs/
reports/
__pycache__/
*.pyc
*.duckdb
*.duckdb.bak
.DS_Store
.env
.vscode/

# --- Keep these! ---
!market_data/.gitkeep
!logs/.gitkeep
!reports/.gitkeep
"""

def run_command(command):
    try:
        result = subprocess.run(
            command, 
            cwd=PROJECT_ROOT, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            shell=True
        )
        print(f"✅ {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e.stderr.strip()}")

def init_structure():
    print(f"🛡️  Initializing Architecture v2.1 in: {PROJECT_ROOT}")
    
    # 1. Define v2.1 Directories
    dirs = [
        "market_data",
        "logs",
        "reports",
        "src/pipeline",
        "src/tools",
        "src/utils",
        "ops"
    ]
    
    for d in dirs:
        dir_path = PROJECT_ROOT / d
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"   Created Directory: {d}/")
            
    # 2. Create .gitkeep files to preserve folder structure
    for d in ["market_data", "logs", "reports"]:
        keep_file = PROJECT_ROOT / d / ".gitkeep"
        if not keep_file.exists():
            with open(keep_file, "w") as f: pass
            
    # 3. Create .gitignore
    gitignore_path = PROJECT_ROOT / ".gitignore"
    if not gitignore_path.exists():
        with open(gitignore_path, "w") as f:
            f.write(GITIGNORE_CONTENT.strip())
        print("✅ Created .gitignore (Excluding Database & Logs)")
        
    # 4. Git Initialization
    if not (PROJECT_ROOT / ".git").exists():
        run_command("git init")
        print("✅ Git Repository Initialized")
    else:
        print("ℹ️  Git Repository already exists.")
        
    print("\n🎉 ARCHITECTURE V2.1 STRUCTURE VERIFIED.")

if __name__ == "__main__":
    init_structure()