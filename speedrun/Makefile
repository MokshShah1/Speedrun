# Speedrun engine harnesses. Run from the repo root or this dir:
#   make -C speedrun bench       # engine perf benchmark (PRD `make bench`)
#   make -C speedrun crash       # hard-kill crash-recovery test
#   make -C speedrun soak        # 20x restart durability test
#   make -C speedrun calibrate   # transfer-model calibration vs baselines
#   make -C speedrun tag-test    # deck auto-tagger self-test
#   make -C speedrun eval        # calibration + interleaving + soak
#   make -C speedrun test        # pure unit tests (no built backend needed)
#
# All targets shell out to Python; the backend-driven ones import the built
# pylib from ../out/pylib, so build the fork first (see README / run.bat).

PY ?= python

.PHONY: bench crash soak calibrate interleave tag-test eval test all

bench:
	$(PY) eval/bench.py

crash:
	$(PY) eval/crash_kill.py

soak:
	$(PY) eval/soak.py

calibrate:
	$(PY) eval/calibration.py

interleave:
	$(PY) eval/interleaving.py

tag-test:
	$(PY) tag_deck.py --self-test

eval: calibrate interleave soak

test:
	$(PY) -m pytest eval/test_eval.py ai/test_ai.py -q

all: test bench crash eval tag-test
