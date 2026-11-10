#!/usr/bin/env bash
# Build "dist/acq4 Tools.app". Run on macOS; the app targets this machine's architecture.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --group build
uv run --group build pyinstaller --noconfirm --clean packaging/acq4_tools.spec

QT_QPA_PLATFORM=offscreen "dist/acq4 Tools.app/Contents/MacOS/acq4-tools" --self-test
echo "Built: dist/acq4 Tools.app"
