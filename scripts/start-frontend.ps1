$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontend = Join-Path $root "frontend"
$ports = @(3000, 3001, 3002, 3003, 3004)
$port = $null

foreach ($candidate in $ports) {
  $open = Test-NetConnection -ComputerName 127.0.0.1 -Port $candidate -InformationLevel Quiet -WarningAction SilentlyContinue
  if (!$open) {
    $port = $candidate
    break
  }
}

if ($null -eq $port) {
  Write-Error "No free frontend port found in: $($ports -join ', ')"
}

Write-Host "Starting frontend on http://127.0.0.1:$port"
$env:PORT = "$port"
Push-Location $frontend
try {
  npm.cmd start
} finally {
  Pop-Location
  Remove-Item Env:\PORT -ErrorAction SilentlyContinue
}
