#!/bin/bash
# Checks if yesterday's evening survey was completed
# Outputs: "MISSING" or "COMPLETE"
# Called by cron survey-morning as data-collection script

CSV="$HOME/.hermes/survey/log.csv"
[ ! -f "$CSV" ] && echo "MISSING" && exit 0

YESTERDAY=$(date -d 'yesterday' '+%Y-%m-%d')

# Check if yesterday has an evening entry (time between 20:00-21:59 with non-empty meds column)
# Evening rows have meds column filled
RESULT=$(tail -20 "$CSV" | grep "$YESTERDAY" | awk -F',' '{
  if ($2 ~ /^(20|21):/ && $3 != "") { found=1 }
} END { if (found) print "COMPLETE"; else print "MISSING" }')

echo "${RESULT:-MISSING}"
