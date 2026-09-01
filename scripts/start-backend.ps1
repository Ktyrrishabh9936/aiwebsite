$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"

if (!(Test-Path $python)) {
  Write-Error "Virtualenv Python not found at $python"
}

Push-Location $backend
try {
  & $python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
} finally {
  Pop-Location
}
