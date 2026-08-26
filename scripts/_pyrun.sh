#!/usr/bin/env bash

# Cross-platform Python launcher for AI log hooks.
# Priority:
# 1. Project Windows virtual environment
# 2. python3
# 3. python
# 4. Windows py launcher
# 5. Common Windows Python locations
#
# Hooks must not block the AI tool if Python cannot be found.

set -u

SCRIPT_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &&
  pwd
)"

PROJECT_ROOT="$(
  cd -- "$SCRIPT_DIR/.." &&
  pwd
)"

VENV_PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"

# Ưu tiên Python trong .venv của chính dự án.
if [ -f "$VENV_PYTHON" ]; then
  exec "$VENV_PYTHON" "$@"
fi

# Các phương án dự phòng.
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$@"
elif command -v python >/dev/null 2>&1; then
  exec python "$@"
elif command -v py.exe >/dev/null 2>&1; then
  exec py.exe -3 "$@"
elif command -v py >/dev/null 2>&1; then
  exec py -3 "$@"
fi

# Tìm Python Windows tại các vị trí phổ biến.
shopt -s nullglob 2>/dev/null || true

for cand in \
  /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
  /mnt/c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
  "/c/Program Files/Python"*/python.exe \
  "/mnt/c/Program Files/Python"*/python.exe \
  "/c/Program Files (x86)/Python"*/python.exe \
  "/mnt/c/Program Files (x86)/Python"*/python.exe \
  /c/Python*/python.exe \
  /mnt/c/Python*/python.exe
do
  if [ -f "$cand" ]; then
    exec "$cand" "$@"
  fi
done

shopt -u nullglob 2>/dev/null || true

# Không tìm thấy Python: thoát thành công để không chặn hook.
exit 0