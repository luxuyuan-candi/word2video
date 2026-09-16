$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

New-Item -ItemType Directory -Force `
  "$root\data\uploads", `
  "$root\data\generated", `
  "$root\data\exports", `
  "$root\data\temp" | Out-Null

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; pnpm install; pnpm dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; if (!(Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
