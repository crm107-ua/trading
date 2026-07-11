/** PM2 — validación MeanRevBB (servidor carlos). */
module.exports = {
  apps: [
    {
      name: "meanrevbb-validation",
      script: "/var/www/html/trader/scripts/server_resume_meanrevbb.sh",
      interpreter: "bash",
      cwd: "/var/www/html/trader",
      env: {
        HYPEROPT_JOB_WORKERS: "1",
        VALIDATION_RUN_ID: "20260709_162954",
        VALIDATION_PROGRESS_INTERVAL: "120",
        PYTHONWARNINGS: "ignore::FutureWarning",
      },
      merge_logs: true,
      log_date_format: "YYYY-MM-DDTHH:mm:ss",
      max_restarts: 0,
      autorestart: false,
      time: true,
      out_file: "/var/www/html/trader/user_data/logs/pm2_meanrevbb.out.log",
      error_file: "/var/www/html/trader/user_data/logs/pm2_meanrevbb.err.log",
    },
  ],
};
