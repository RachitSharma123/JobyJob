#!/bin/bash
# Run this once on VPS to set up cron jobs
# chmod +x setup_cron.sh && ./setup_cron.sh

PROJ="/home/rachit/.openclaw/workspace/consulting_applier"
PYTHON="python3"

# Scraper cron: 6 AM daily Melbourne time (UTC+10/11)
# 6 AM AEDT (UTC+11) = 7 PM UTC previous day
CRON_SCRAPER="0 19 * * * cd $PROJ && $PYTHON orchestrator/daily_runner.py >> logs/runner.log 2>&1"

# Bot server: start on reboot
CRON_BOT="@reboot cd $PROJ && uvicorn bot.bot_server:app --host 0.0.0.0 --port 8765 >> logs/bot_server.log 2>&1"

# Add to crontab
(crontab -l 2>/dev/null; echo "$CRON_SCRAPER") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_BOT") | crontab -

echo "Cron jobs added:"
crontab -l
