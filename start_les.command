#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/.venv/bin/python3"
[ -x "$PY" ] || PY="/usr/bin/python3"
exec "$PY" "$DIR/tools/les_runtime_control.py" start-core --include-ui --open-ui
