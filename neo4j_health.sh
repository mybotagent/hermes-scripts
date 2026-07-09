#!/bin/bash
# Neo4j health check cron — silent when healthy, alert on failure
# Runs daily at 08:00 KST (07:00 cron TZ)
source ~/.venv-neo4j/bin/activate 2>/dev/null || source /home/ubuntu/.venv-neo4j/bin/activate
cd /home/ubuntu/hermes-wiki-super/.metagraph
python3 check_health.py 2>&1
RC=$?
if [ $RC -eq 0 ]; then
  exit 0  # silent
fi
echo "❌ Neo4j Health Check FAILED"
python3 check_health.py --verbose --repair 2>&1
exit 1
