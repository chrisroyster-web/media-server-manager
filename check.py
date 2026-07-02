#!/usr/bin/env python3
"""
check.py - Verify all Python files in the project parse correctly.
Run: python check.py
"""

import ast
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SKIP = {"dist", "__pycache__", ".git", "build"}

CRITICAL_ENDINGS = {
    "main.py": "if __name__",
}

failures = []
warnings = []

py_files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP]
    for fname in filenames:
        if fname.endswith(".py"):
            py_files.append(os.path.join(dirpath, fname))

py_files.sort()

print("Checking {} Python files...\n".format(len(py_files)))

for path in py_files:
    rel = os.path.relpath(path, ROOT)
    try:
        src = open(path, encoding="utf-8").read()
    except Exception as e:
        failures.append((rel, "Cannot read: {}".format(e)))
        continue

    # Syntax check
    try:
        ast.parse(src)
    except SyntaxError as e:
        failures.append((rel, "SyntaxError line {}: {}".format(e.lineno, e.msg)))
        continue

    # Truncation heuristics
    lines = src.splitlines()
    if len(lines) == 0:
        failures.append((rel, "File is empty"))
        continue

    last = lines[-1].strip()
    # A non-empty file ending mid-string or mid-expression is suspicious
    if last.endswith("\\") or last.endswith(",") or last.endswith("("):
        warnings.append((rel, "Last line looks truncated: {!r}".format(last)))

    # Critical content checks
    for fname, required in CRITICAL_ENDINGS.items():
        if path.endswith(fname) and required not in src:
            failures.append((rel, "Missing required content: '{}'".format(required)))

    print("  OK  {}  ({} lines)".format(rel, len(lines)))

print()

if warnings:
    print("WARNINGS:")
    for rel, msg in warnings:
        print("  WARN  {}  —  {}".format(rel, msg))
    print()

if failures:
    print("FAILURES:")
    for rel, msg in failures:
        print("  FAIL  {}  —  {}".format(rel, msg))
    print()
    sys.exit(1)
else:
    print("All files OK{}.".format(
        " ({} warning{})".format(len(warnings), "s" if len(warnings) != 1 else "")
        if warnings else ""
    ))
