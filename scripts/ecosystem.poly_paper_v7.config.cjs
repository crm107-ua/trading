/** PM2 — solo paper maker_edge v7 lock (no arranca otros apps).
 *  Uso:
 *    cd /var/www/html/trader
 *    pm2 start scripts/ecosystem.poly_paper_v7.config.cjs
 *    pm2 logs poly-paper-v7
 *    pm2 stop poly-paper-v7
 */
module.exports = {
  apps: [
    {
      name: "poly-paper-v7",
      script: "/var/www/html/trader/scripts/server_poly_paper_v7.sh",
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
      },
      merge_logs: true,
      log_date_format: "YYYY-MM-DDTHH:mm:ss",
      // Un solo batch; si termina (HIT/streak/fin) no reiniciar en bucle
      max_restarts: 0,
      autorestart: false,
      time: true,
      out_file: "/var/www/html/trader/user_data/logs/pm2_poly_paper_v7.out.log",
      error_file: "/var/www/html/trader/user_data/logs/pm2_poly_paper_v7.err.log",
    },
  ],
};
