#!/bin/bash
# Simple test runner script

echo "Running audtag test suite..."
echo "============================"
echo ""

uv run --script run_tests.py "$@"