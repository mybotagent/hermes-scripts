#!/usr/bin/env bash
# sync_survey_repo.sh — Push survey log + heatmap PNG to GitHub repo
set -e

SRC="$HOME/.hermes/survey/log.csv"
DST="$HOME/daily-survey/log.csv"
HEATMAP_SRC="$HOME/.hermes/survey/heatmap_latest.png"
HEATMAP_DST="$HOME/daily-survey/heatmap.png"
GEN_SCRIPT="$HOME/.hermes/survey/gen_heatmap.py"

# 1. Copy latest CSV data
cp "$SRC" "$DST"

# 2. Regenerate heatmap PNG from latest CSV
python3 "$GEN_SCRIPT"

# 3. Copy heatmap to repo (overwrite atomically)
cp "$HEATMAP_SRC" "$HEATMAP_DST"

cd "$HOME/daily-survey"

# 4. If nothing changed, exit silently
if git diff --quiet; then
    echo "No changes to survey repo"
    exit 0
fi

# 5. Commit & push
git add log.csv heatmap.png
git commit -m "update: survey data + heatmap $(date '+%Y-%m-%d')"
git push origin main
echo "Pushed survey update + heatmap: $(date '+%Y-%m-%d %H:%M')"