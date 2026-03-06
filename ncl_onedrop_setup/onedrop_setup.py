
#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

VENv = ROOT / '.venv'
REQ = ROOT / 'backend' / 'requirements.txt'

def sh(cmd):
    print('> ', cmd)
    return subprocess.call(cmd, shell=True)  # noqa: S602

def install():
    if not VENv.exists():
        sh(f"python -m venv {VENv}")
    pip = VENv / 'Scripts' / 'pip.exe'
    sh(f"{pip} install -r {REQ}")
    print("\n[Done] Virtual env ready. To run API:")
    print(f"{VENv}/Scripts/activate.ps1")
    print("python -m uvicorn backend.api.main:app --reload --port 8123")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'install':
        install()
    else:
        print("Usage: python3 onedrop_setup.py install")
