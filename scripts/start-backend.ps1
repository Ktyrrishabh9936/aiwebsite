param([switch]$Reload)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"

if (!(Test-Path $python)) {
  Write-Error "Virtualenv Python not found at $python"
}

& $python -c "import boto3" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Error "Backend dependency boto3 is missing. Run: .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt"
}

Push-Location $backend
try {
  if ($Reload) {
    & $python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
  } else {
    & $python -m uvicorn server:app --host 127.0.0.1 --port 8000
  }
} finally {
  Pop-Location
}
