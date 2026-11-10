# Build dist\acq4-tools\acq4-tools.exe. Run on Windows.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

uv sync --group build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --group build pyinstaller --noconfirm --clean packaging/acq4_tools.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$env:QT_QPA_PLATFORM = "offscreen"
# Start-Process -Wait because a windowed executable otherwise returns immediately.
$test = Start-Process -FilePath "dist\acq4-tools\acq4-tools.exe" -ArgumentList "--self-test" -Wait -PassThru
if ($test.ExitCode -ne 0) { throw "Self-test failed" }
Write-Host "Built: dist\acq4-tools\acq4-tools.exe"
