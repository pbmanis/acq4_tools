#!/usr/bin/env bash
# Build dist/acq4-tools/acq4-tools. Run on Linux; build on the oldest distribution
# you need to support, since the program depends on the build machine's glibc.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --group build
uv run --group build pyinstaller --noconfirm --clean packaging/acq4_tools.spec

QT_QPA_PLATFORM=offscreen dist/acq4-tools/acq4-tools --self-test
echo "Built: dist/acq4-tools/acq4-tools"
