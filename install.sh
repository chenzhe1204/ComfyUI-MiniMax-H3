#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install this node package into ComfyUI/custom_nodes as a symlink.
# This is a development convenience; installing by clone or the ComfyUI
# Registry/Manager is equally valid.
#
# Usage:
#   ./install.sh /path/to/ComfyUI
#   COMFYUI_DIR=/path/to/ComfyUI ./install.sh
set -eu

SRC_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
COMFYUI_DIR=${1:-${COMFYUI_DIR:-$HOME/ComfyUI}}
CUSTOM_NODES_DIR="$COMFYUI_DIR/custom_nodes"
DEST="$CUSTOM_NODES_DIR/comfyui-minimax-h3"

if [ ! -d "$COMFYUI_DIR" ]; then
    echo "error: ComfyUI directory not found: $COMFYUI_DIR" >&2
    echo "Usage: ./install.sh /path/to/ComfyUI" >&2
    exit 1
fi
if [ ! -d "$CUSTOM_NODES_DIR" ]; then
    echo "error: custom_nodes directory not found: $CUSTOM_NODES_DIR" >&2
    exit 1
fi

if [ -L "$DEST" ]; then
    echo "Replacing existing symlink: $DEST"
    rm "$DEST"
elif [ -e "$DEST" ]; then
    echo "error: $DEST already exists and is not a symlink." >&2
    echo "Remove it manually if you want to reinstall." >&2
    exit 1
fi

ln -s "$SRC_DIR" "$DEST"
echo "Installed: $DEST -> $SRC_DIR"
echo
echo "Next steps:"
echo "  1. Build the pinned h3.c if you have not already:"
echo "       $SRC_DIR/scripts/bootstrap_h3.sh"
echo "  2. Download the model weights from the official MiniMax source."
echo "     The weights are NOT included and have a separate license with"
echo "     territorial restrictions."
echo "  3. Configure H3_MODEL_DIR/H3_BIN or:"
echo "       $COMFYUI_DIR/user/default/comfyui-minimax-h3.json"
echo "  4. Restart ComfyUI and search for 'MiniMax H3'."
echo "  5. Diagnose with:"
echo "       python \"$SRC_DIR/scripts/doctor.py\" --mode ref2va"
