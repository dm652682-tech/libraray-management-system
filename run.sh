#!/usr/bin/env bash
# One-command start for Mac / Linux:  bash run.sh
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
export SECRET_KEY="${SECRET_KEY:-change-me-to-a-long-random-text}"
python app.py
