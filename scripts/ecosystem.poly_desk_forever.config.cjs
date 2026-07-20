/** PM2 — desk REAL infinito + informe email cada 3h.
 *
 *  cd /var/www/html/trader
 *  pm2 start scripts/ecosystem.poly_desk_forever.config.cjs
 *  pm2 save
 *  pm2 logs poly-desk-forever
 *  pm2 stop poly-desk-forever   # único stop manual
 */
module.exports = {
  apps: [
    {
      name: "poly-desk-forever",
      script: "/var/www/html/trader/scripts/server_poly_desk_forever.sh",
      interpreter: "bash",
      cwd: "/var/www/html/trader",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONIOENCODING: "utf-8",
        NVIDIA_NIM_MODE: "hybrid",
        NVIDIA_NIM_PROFIT_ASSIST: "1",
        POLY_LIVE_DAY_LOSS_DISABLE: "1",
        POLY_LIVE_BYPASS_CHECKLIST: "1",
        POLY_DESK_MINUTES: "12",
        POLY_DESK_CAPITAL: "5",
        POLY_DESK_CONFIG: "maker_demo_promo_pulse_micro5_scalp.json",
        POLY_DESK_PAUSE_S: "45",
        POLY_DESK_MIN_BALANCE: "1",
        POLY_LIVE_MIN_BALANCE_PUSD: "1",
        POLY_LIVE_MAX_CAPITAL_USDC: "5",
        POLY_DESK_EMAIL_EVERY_S: "10800",
        MAIL_TO: "caromamusic@gmail.com",
      },
      merge_logs: true,
      log_date_format: "YYYY-MM-DDTHH:mm:ss",
      // Si se queda sin fondos el proceso hace `pm2 stop` (status stopped).
      // Tras crash inesperado sí reinicia; tras stop manual/sin fondos NO.
      autorestart: true,
      stop_exit_codes: [0],
      max_restarts: 20,
      min_uptime: 10000,
      restart_delay: 15000,
      kill_timeout: 20000,
      time: true,
      out_file: "/var/www/html/trader/user_data/logs/pm2_poly_desk_forever.out.log",
      error_file: "/var/www/html/trader/user_data/logs/pm2_poly_desk_forever.err.log",
    },
  ],
};
