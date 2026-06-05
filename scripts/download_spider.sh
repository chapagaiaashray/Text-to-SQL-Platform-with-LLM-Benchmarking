#!/usr/bin/env bash
# =============================================================
#  Download the Spider 1.0 dataset into data/spider/.
#
#  Spider is hosted on Google Drive and (mirrored) on Hugging Face.
#  Hosting has moved over the years, so VERIFY the current link at:
#      https://yale-lily.github.io/spider
#
#  This script tries Hugging Face first (most stable), then gdown.
#  Run from the project root:  bash scripts/download_spider.sh
# =============================================================
set -euo pipefail

DEST="data/spider"
mkdir -p "$DEST"

echo "==> Spider download"
echo "    Destination: $DEST"

# -------- Option A: Hugging Face mirror (recommended) --------
# The community mirror 'xlangai/spider' tracks the official release.
# Requires: pip install datasets
if python3 -c "import datasets" 2>/dev/null; then
    echo "==> Found 'datasets'. Pulling JSON splits + tables from Hugging Face mirror..."
    python3 - <<'PY'
from datasets import load_dataset
import json, os, pathlib

dest = pathlib.Path("data/spider")
dest.mkdir(parents=True, exist_ok=True)

# Splits: train + validation (Spider calls validation "dev").
ds = load_dataset("xlangai/spider")
for split, fname in (("train", "train_spider.json"), ("validation", "dev.json")):
    rows = [dict(r) for r in ds[split]]
    (dest / fname).write_text(json.dumps(rows, indent=2))
    print(f"   wrote {fname}: {len(rows)} examples")
print("NOTE: This mirror provides questions+gold SQL but NOT the raw")
print("      SQLite database files or tables.json schema file.")
print("      For those, use Option B below (full archive).")
PY
fi

# -------- Option B: full archive (databases + tables.json) --------
# The benchmarking pipeline NEEDS the SQLite databases and tables.json,
# which only the full archive provides. gdown handles Google Drive.
echo ""
echo "==> For the FULL archive (SQLite DBs + tables.json), you need the"
echo "    Google Drive archive. Install gdown and run:"
echo ""
echo "      pip install gdown"
echo "      # Get the CURRENT file id/link from https://yale-lily.github.io/spider"
echo "      gdown --fuzzy 'https://drive.google.com/uc?id=<SPIDER_ZIP_FILE_ID>' -O data/spider/spider.zip"
echo "      unzip data/spider/spider.zip -d data/spider/"
echo ""
echo "    After unzip you should have, under data/spider/ (paths vary by release):"
echo "      tables.json            <- schema of every database"
echo "      train_spider.json      <- ~7000 training examples"
echo "      dev.json               <- ~1034 dev examples"
echo "      database/<db_id>/<db_id>.sqlite   <- 200 SQLite databases"
echo ""
echo "==> Once files are in place, verify with:  python scripts/explore_spider.py"
