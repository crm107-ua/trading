/** PM2 — overnight autotune paper (solo esta app).
 *  cd /var/www/html/trader
 *  pm2 start scripts/ecosystem.poly_overnight.config.cjs
 *  pm2 logs poly-overnight
 */
module.exports = {
  apps: [
    {
      name: "poly-overnight",
      script: "/var/www/html/trader/scripts/server_poly_overnight.sh",
      interpreter: "bash",
      cwd: "/var/www/html/trader",
      env: {
        PYTHONUNBUFFERED: "1",
        POLY_DISABLE_AUTONOMOUS_OOS: "1",
        BATCH_STOP_AFTER_LOSS_STREAK: "2",
        NVIDIA_NIM_MODE: "hybrid",
        NVIDIA_NIM_PROFIT_ASSIST: "1",
        NVIDIA_NIM_STRONG_EDGE_MULT: "2.0",
        NVIDIA_NIM_EXIT_EVERY_S: "2",
        OVERNIGHT_MAX_TRIALS: "12",
        OVERNIGHT_HIT_WR: "0.5",
        OVERNIGHT_HIT_AVG: "8",
        OVERNIGHT_HIT_TOTAL: "40",
        MAIL_TO: "caromamusic@gmail.com",
      },
      merge_logs: true,
      log_date_format: "YYYY-MM-DDTHH:mm:ss",
      max_restarts: 2,
      min_uptime: 10000,
      autorestart: true,
      restart_delay: 30000,
      time: true,
      out_file: "/var/www/html/trader/user_data/logs/pm2_poly_overnight.out.log",
      error_file: "/var/www/html/trader/user_data/logs/pm2_poly_overnight.err.log",
    },
  ],
};
