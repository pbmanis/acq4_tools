#!/usr/bin/env bash
# Build dist/acq4-tools/acq4-tools.exe. Run from Git Bash on Windows.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --group build
uv run --group build pyinstaller --noconfirm --clean packaging/acq4_tools.spec

# Wait for the windowed executable to finish; direct launches may return early.
powershell.exe -NoProfile -Command '
    $env:QT_QPA_PLATFORM = "offscreen"
    $test = Start-Process -FilePath "dist\acq4-tools\acq4-tools.exe" -ArgumentList "--self-test" -Wait -PassThru
    if ($test.ExitCode -ne 0) { exit $test.ExitCode }
'
echo "Built: dist/acq4-tools/acq4-tools.exe"
