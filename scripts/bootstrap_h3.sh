#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Clone and build the pinned upstream h3.c CLI into third_party/h3.c.
# This does NOT download model weights and does NOT accept the model license
# on your behalf.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST=${1:-"$ROOT/third_party/h3.c"}
H3_REPO=${H3_REPO:-https://github.com/antirez/h3.c.git}
H3_COMMIT=${H3_COMMIT:-8974cc055ea9c02fcd14cc27dfda3e1027c05153}

echo "h3.c repository: $H3_REPO"
echo "pinned commit:   $H3_COMMIT"
echo "destination:     $DEST"

if [ -e "$DEST" ] && [ ! -d "$DEST/.git" ]; then
    echo "error: $DEST exists but is not a git checkout." >&2
    exit 1
fi

if [ ! -d "$DEST/.git" ]; then
    mkdir -p "$(dirname "$DEST")"
    git clone "$H3_REPO" "$DEST"
else
    git -C "$DEST" fetch --tags origin
fi

if ! git -C "$DEST" checkout "$H3_COMMIT"; then
    echo "error: commit $H3_COMMIT is not available in $DEST." >&2
    exit 1
fi

echo
echo "Building h3..."
if command -v sysctl >/dev/null 2>&1; then
    JOBS=$(sysctl -n hw.ncpu 2>/dev/null || echo 4)
else
    JOBS=4
fi
make -C "$DEST" -j"$JOBS"

cat <<EOF

Built: $DEST/h3

Next steps:
  1. Download the MiniMax H3 weights from the official Hugging Face repository.
     The model is NOT included and is governed by the MiniMax H3 Community
     License Agreement (the Applicable Territory excludes the EU, UK, South
     Korea, and the USA):
       hf download MiniMaxAI/MiniMax-H3 \\
         --include "model_index.json" "FL2VA/*" "Ref2VA/*" \\
         --local-dir "$ROOT/MiniMax-H3"

  2. Configure the paths:
       export H3_BIN="$DEST/h3"
       export H3_MODEL_DIR="$ROOT/MiniMax-H3"
     or create ComfyUI/user/default/comfyui-minimax-h3.json:
       {"h3_dir": "$DEST", "model_dir": "$ROOT/MiniMax-H3"}

  3. Run the doctor:
       python "$ROOT/scripts/doctor.py" --mode ref2va
EOF
