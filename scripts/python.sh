#!/bin/sh
# Prints the Python this repo's scripts and hooks run with: $PYTHON, else the repo's own .venv, else the active
# virtualenv, else python3. The repo's .venv comes before an active one because an environment left active from
# another checkout runs that checkout's code, silently (an editable install of the same package elsewhere).
# Always an absolute path when it is a file, so it still works after a `cd`.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "${PYTHON:-}" ]; then
  echo "$PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ] && "$ROOT/.venv/bin/python" -c "" 2>/dev/null; then
  if [ -n "${VIRTUAL_ENV:-}" ] && [ "$(cd "$VIRTUAL_ENV" 2>/dev/null && pwd)" != "$ROOT/.venv" ]; then
    echo "note: ignoring the active environment $VIRTUAL_ENV; using this repo's .venv" >&2
  fi
  echo "$ROOT/.venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  echo "$VIRTUAL_ENV/bin/python"
else
  echo "python3"
fi
