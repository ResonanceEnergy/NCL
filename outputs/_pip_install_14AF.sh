#!/bin/bash
PIP=/opt/homebrew/bin/python3
for pkg in datasketch ccxt feedparser; do
  echo "=== installing $pkg"
  $PIP -m pip install --break-system-packages "$pkg" 2>&1 | tail -2
done

# Larger packages individually, with timeout-safe execution
for pkg in spacy sentence-transformers transformers; do
  echo "=== installing $pkg (larger)"
  $PIP -m pip install --break-system-packages "$pkg" 2>&1 | tail -2
done

echo "=== verifying imports"
$PIP -c '
import importlib
for m in ("datasketch","ccxt","feedparser","spacy","sentence_transformers","transformers"):
    try:
        v = importlib.import_module(m).__version__
        print(f"  {m}: {v}")
    except Exception as e:
        print(f"  {m}: FAIL {type(e).__name__}")
'
