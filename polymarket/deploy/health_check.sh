#!/bin/bash
# Daily health check — add to crontab on Hetzner:
#   0 8 * * * /opt/trading/polymarket/deploy/health_check.sh >> /var/log/poly16_health.log 2>&1

set -euo pipefail
cd /opt/trading
python3 -m polymarket.research.collectors.health_check
