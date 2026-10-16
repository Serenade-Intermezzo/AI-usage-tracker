#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$project_dir/.venv-gui/bin/python" ]; then
  exec "$project_dir/.venv-gui/bin/python" "$project_dir/gui/main.py"
fi
exec /usr/bin/python3 "$project_dir/gui/main.py"
