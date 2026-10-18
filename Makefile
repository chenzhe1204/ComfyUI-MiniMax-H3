# SPDX-License-Identifier: GPL-3.0-or-later

PYTHON ?= python3

.PHONY: test integration lint doctor

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

integration:
	@test -n "$$COMFYUI_DIR" || (echo "Set COMFYUI_DIR to a ComfyUI checkout" >&2; exit 1)
	COMFYUI_DIR="$$COMFYUI_DIR" $(PYTHON) -m unittest tests.check_nodes_integration -v

lint:
	$(PYTHON) -m ruff check .

doctor:
	$(PYTHON) scripts/doctor.py --mode ref2va
