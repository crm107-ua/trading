# PM2 ecosystem — Phase A #16 on Hetzner (Linux)
# Usage (from repo root on server):
#   cd /opt/trading && pm2 start polymarket/deploy/ecosystem.config.cjs
#   pm2 save

module.exports = {
  apps: [
    {
      name: "poly16-btc-feed",
      cwd: "/opt/trading",
      script: "python3",
      args: "-m polymarket.research.collectors.daemon_btc_feed",
      interpreter: "none",
      autorestart: true,
      max_restarts: 100,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: "poly16-clob-rec",
      cwd: "/opt/trading",
      script: "python3",
      args: "-m polymarket.research.collectors.daemon_clob_recorder",
      interpreter: "none",
      autorestart: true,
      max_restarts: 100,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
