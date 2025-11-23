import os
import subprocess
from pathlib import Path

# Define Project Root
PROJECT_ROOT = Path(__file__).parent.resolve()

# The Rules of what to Ignore (The .gitignore)
GITIGNORE_CONTENT = """
# --- Data & Logs (Local Only) ---
market_data/
logs/
__pycache__/
*.pyc
.DS_Store
.env
.vscode/

# --- Keep these! ---
!market_data/.gitkeep
!logs/.gitkeep
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

def init_repo():
    print(f"🛡️  Initializing Git Repository in: {PROJECT_ROOT}")
    
    # 1. Create .gitignore
    gitignore_path = PROJECT_ROOT / ".gitignore"
    if not gitignore_path.exists():
        with open(gitignore_path, "w") as f:
            f.write(GITIGNORE_CONTENT.strip())
        print("✅ Created .gitignore (Excluding Database & Logs)")
    
    # 2. Create .gitkeep files to preserve folder structure
    (PROJECT_ROOT / "market_data").mkdir(exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    
    with open(PROJECT_ROOT / "market_data" / ".gitkeep", "w") as f: pass
    with open(PROJECT_ROOT / "logs" / ".gitkeep", "w") as f: pass

    # 3. Git Commands
    run_command("git init")
    run_command("git add .")
    run_command('git commit -m "Initial Commit: V2.0 Golden Architecture"')
    
    print("\n🎉 REPOSITORY SECURED.")
    print("   You can now safely experiment. If you break something, just run:")
    print("   'git checkout .'")

if __name__ == "__main__":
    init_repo()