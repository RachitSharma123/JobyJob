#!/bin/bash
# One-shot install on VPS
# Run from: /home/rachit/.openclaw/workspace/consulting_applier
# chmod +x install.sh && ./install.sh

set -e
echo "=== Installing consulting_applier ==="

# 1. Python deps
echo "Installing Python packages..."
pip3 install -r requirements.txt --break-system-packages

# 2. Playwright Chromium
echo "Installing Playwright Chromium..."
playwright install chromium --with-deps

# 3. DB migration
echo "Running DB migration..."
python3 db/supabase_client.py

# 4. Test scrapers (dry run)
echo "Testing scrapers (dry run)..."
python3 orchestrator/daily_runner.py --dry-run --ats lever

# 5. Test Telegram
echo "Testing Telegram..."
python3 bot/telegram_notifier.py

echo ""
echo "=== Install complete ==="
echo ""
echo "Next steps:"
echo "  1. Update candidate_profile.json with your real details"
echo "  2. Set Telegram webhook:"
echo "     python3 bot/bot_server.py --set-webhook https://YOUR_VPS_IP:8765/webhook"
echo "  3. Start bot server:"
echo "     uvicorn bot.bot_server:app --host 0.0.0.0 --port 8765"
echo "  4. Set up cron:"
echo "     ./setup_cron.sh"
echo "  5. Full run:"
echo "     python3 orchestrator/daily_runner.py"
