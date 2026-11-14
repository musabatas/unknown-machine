#!/bin/bash
# Writes /logs/verifier/reward.txt from the sidecar's signed result.
# /usr/bin/python3 -I: absolute path and isolated mode, so nothing the agent left
# on PATH, in the working directory or in PYTHON* variables is picked up.
exec /usr/bin/python3 -I /tests/verify.py
