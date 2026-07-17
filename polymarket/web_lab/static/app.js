/* Poly Desk — selector de modos (sin frases) */
(() => {
  const $ = (id) => document.getElementById(id);
  let strategies = [];
  let currentRunId = null;
  let es = null;
  let health = null;

  const MODE_COPY = {
    paper: {
      title: "Paper — simulación",
      chip: "PAPER",
      chipClass: "ok",
      banner: false,
      points: [
        "Usa precios reales de Binance + order book Polymarket.",
        "No envía ninguna orden on-chain.",
        "Ideal para probar metodologías y capital.",
      ],
    },
    live_dry: {
      title: "Live dry-run — ensayo",
      chip: "DRY",
      chipClass: "warn",
      banner: "dry",
      bannerTitle: "Live · dry-run",
      bannerText: "Misma lógica que el live real, pero solo registra WOULD_POST. No gasta pUSD.",
      points: [
        "Conecta a tu wallet / CLOB (lee saldo).",
        "Calcula quotes y simula el post (POST DRY_RUN).",
        "Cero riesgo de fondos; valida que el cableado funciona.",
      ],
    },
    live_real: {
      title: "Live real — dinero real",
      chip: "REAL",
      chipClass: "danger",
      banner: "real",
      bannerTitle: "Live · dinero real",
      bannerText: "Envía órdenes GTC post-only con tu pUSD. 1 sesión · respeta el tope USDC.",
      points: [
        "Órdenes maker reales en Polymarket.",
        "Marca la casilla de aceptar riesgo antes de ejecutar.",
        "Parar cancela órdenes abiertas (best-effort).",
      ],
    },
  };

  const chart = new Chart($("equityChart"), {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Equity €",
          data: [],
          borderColor: "#e8a45a",
          backgroundColor: "rgba(232,164,90,0.12)",
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: "index",
          intersect: false,
          backgroundColor: "#1c1814",
          titleColor: "#f3ebe2",
          bodyColor: "#e8a45a",
          borderColor: "#3a322a",
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          ticks: { color: "#a89888", maxTicksLimit: 8 },
          grid: { color: "rgba(58,50,42,0.45)" },
        },
        y: {
          ticks: {
            color: "#a89888",
            callback: (v) => v.toFixed(2) + "€",
          },
          grid: { color: "rgba(58,50,42,0.45)" },
        },
      },
    },
  });

  function fmt(n, d = 2) {
    if (n == null || Number.isNaN(n)) return "—";
    const x = Number(n);
    return (x >= 0 ? "+" : "") + x.toFixed(d);
  }

  function setPnlClass(el, v) {
    el.classList.remove("up", "down");
    if (v > 0) el.classList.add("up");
    if (v < 0) el.classList.add("down");
  }

  function currentMode() {
    return $("runMode").value || "paper";
  }

  function applyModeUi() {
    const mode = currentMode();
    const c = MODE_COPY[mode];
    $("modeExplain").innerHTML = `
      <span class="title">${c.title}</span>
      <ul>${c.points.map((p) => `<li>${p}</li>`).join("")}</ul>`;

    $("pill-mode").textContent = c.chip;
    $("chip-mode").className = "stat-chip " + c.chipClass;

    const banner = $("liveBanner");
    if (c.banner) {
      banner.hidden = false;
      banner.className = "live-banner " + (c.banner === "dry" ? "dry" : "");
      $("liveBannerTitle").textContent = c.bannerTitle;
      $("liveBannerText").textContent = c.bannerText;
    } else {
      banner.hidden = true;
    }

    const isLive = mode !== "paper";
    $("liveCaps").hidden = !isLive;
    $("acceptWrap").hidden = mode !== "live_real";
    $("sessions").disabled = isLive;
    if (isLive) $("sessions").value = "1";

    $("btnRun").classList.toggle("danger", mode === "live_real");
    $("btnRun").textContent =
      mode === "paper" ? "Ejecutar" : mode === "live_dry" ? "Ejecutar dry-run" : "Ejecutar LIVE";

    $("armHint").textContent =
      mode === "live_real"
        ? "Tope live limita el capital máximo. Marca la casilla para habilitar dinero real."
        : mode === "live_dry"
          ? "Dry-run no mueve fondos. Úsalo para validar el cableado CLOB."
          : "Paper no usa wallet ni pUSD.";
  }

  function renderStratCard(s) {
    if (!s) return;
    const m = s.metrics || {};
    $("stratCard").innerHTML = `
      <div class="name">${s.name}</div>
      <div class="blurb">${s.blurb || ""}</div>
      <div class="meta">
        <span class="chip">${s.badge || "—"}</span>
        <span class="chip">WR ${m.wr != null ? (100 * m.wr).toFixed(0) + "%" : "—"}</span>
        <span class="chip">total ${m.total != null ? fmt(m.total) + "€" : "—"}</span>
        <span class="chip">size ${s.params_preview?.size ?? "—"}</span>
        <span class="chip">edge ${s.params_preview?.edge ?? "—"}</span>
        <span class="chip">lock ${s.params_preview?.lock ?? "—"}</span>
      </div>`;
    if (currentMode() === "paper") {
      $("sessions").value = s.default_sessions || 4;
    }
    $("minutes").value = s.default_minutes || 5;
  }

  async function loadHealth() {
    health = await fetch("/api/health").then((r) => r.json());
    const live = health.live || {};
    const bal = live.balance_pusd;
    $("balPusd").textContent = bal == null ? "—" : Number(bal).toFixed(2);
    $("chip-balance").className = "stat-chip " + (bal > 0 ? "ok" : "warn");

    const level = health.level || "safe";
    $("pill-arm").textContent = level.toUpperCase();
    $("chip-arm").className =
      "stat-chip " + (level === "real" ? "danger" : level === "dry" ? "warn" : "ok");

    if (live.max_capital_usdc != null) {
      $("armMax").value = live.max_capital_usdc;
    }
    applyModeUi();
  }

  async function loadStrategies() {
    const data = await fetch("/api/strategies").then((r) => r.json());
    strategies = data.strategies || [];
    const sel = $("strategy");
    sel.innerHTML = "";
    strategies.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.badge || ""} · ${s.name}`;
      sel.appendChild(opt);
    });
    if (strategies.length) {
      const pref =
        strategies.find((x) => x.id === "micro_5") ||
        strategies.find((x) => x.id === "t4_risk_up") ||
        strategies[0];
      sel.value = pref.id;
      renderStratCard(pref);
    }
    sel.addEventListener("change", () => {
      renderStratCard(strategies.find((x) => x.id === sel.value));
    });
  }

  function resetUi(capital) {
    chart.data.labels = ["start"];
    chart.data.datasets[0].data = [capital];
    chart.update("none");
    $("sessBody").innerHTML = "";
    $("logs").textContent = "";
    $("kpiEquity").textContent = capital.toFixed(2) + "€";
    $("kpiPnl").textContent = "+0.00";
    $("kpiWr").textContent = "—";
    $("kpiPct").textContent = "0%";
    setPnlClass($("kpiPnl"), 0);
  }

  function applySnapshot(d) {
    if (!d) return;
    $("kpiEquity").textContent = Number(d.equity).toFixed(2) + "€";
    $("kpiPnl").textContent = fmt(d.pnl) + "€";
    setPnlClass($("kpiPnl"), d.pnl);
    $("kpiWr").textContent =
      d.traded > 0 ? (100 * d.wr).toFixed(0) + `% (${d.wins}W/${d.losses}L)` : "—";
    const sessPct =
      d.session_n > 0
        ? ((Math.max(d.session_i - 1, 0) + d.pct / 100) / d.session_n) * 100
        : d.pct;
    $("kpiPct").textContent = `${sessPct.toFixed(0)}% · S${d.session_i || 0}/${d.session_n || 0}`;
    $("pill-run").textContent = (d.status || "—").toUpperCase();
    $("chip-run").className =
      "stat-chip " +
      (d.status === "running" ? "ok" : d.status === "error" ? "danger" : "");
    $("runMeta").textContent = `${d.mode || "paper"}${d.dry_run ? "·dry" : ""} · ${d.strategy_name || ""}`;

    const pts = d.equity_points || [];
    if (pts.length) {
      chart.data.labels = pts.map((_, i) => (i === 0 ? "0" : String(i)));
      chart.data.datasets[0].data = pts.map((p) => p.equity);
      chart.update("none");
    }

    let eq = Number(d.capital);
    $("sessBody").innerHTML = (d.nets || [])
      .map((n, i) => {
        eq += n;
        const cls = n > 0 ? "win" : n < 0 ? "loss" : "flat";
        const tag = n > 0 ? "WIN" : n < 0 ? "LOSS" : "FLAT";
        return `<tr>
          <td>S${i + 1}</td>
          <td class="${cls}">${tag}</td>
          <td class="${cls}">${fmt(n)}€</td>
          <td>${eq.toFixed(2)}€</td>
        </tr>`;
      })
      .join("");

    $("btnRun").disabled = d.status === "running";
    $("btnStop").disabled = d.status !== "running";
  }

  function appendLog(line) {
    const box = $("logs");
    const div = document.createElement("div");
    if (/error|traceback|fail|bloqueado/i.test(line)) div.className = "err";
    else if (/net=\+|HIT|WIN|FILL /i.test(line)) div.className = "ok";
    else if (/POST LIVE|POST DRY|LIVE/i.test(line)) div.className = "live";
    div.textContent = line;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    while (box.children.length > 400) box.removeChild(box.firstChild);
  }

  function connectStream(runId) {
    if (es) es.close();
    es = new EventSource(`/api/runs/${runId}/stream`);
    es.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "ping") return;
      if (msg.type === "log" && msg.line) appendLog(msg.line);
      if (msg.data) applySnapshot(msg.data);
      if (
        msg.type === "done" ||
        (msg.data && ["done", "error", "stopped"].includes(msg.data.status))
      ) {
        $("btnRun").disabled = false;
        $("btnStop").disabled = true;
        es.close();
        loadHealth();
      }
    };
  }

  async function syncLiveLevelIfNeeded(runMode) {
    if (runMode === "paper") return;
    const level = runMode === "live_real" ? "real" : "dry";
    await fetch("/api/live/level", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        level,
        max_capital: Number($("armMax").value || 5),
      }),
    });
  }

  $("runMode").addEventListener("change", applyModeUi);

  $("btnRun").addEventListener("click", async () => {
    const run_mode = currentMode();
    if (run_mode === "live_real" && !$("acceptReal").checked) {
      appendLog("ERROR: marca «Acepto usar dinero real» para live real.");
      return;
    }
    const strategy_id = $("strategy").value;
    const capital = Number($("capital").value);
    const sessions = run_mode === "paper" ? Number($("sessions").value) : 1;
    const minutes = Number($("minutes").value);
    resetUi(capital);
    $("btnRun").disabled = true;
    appendLog(`→ ${run_mode} ${strategy_id} capital=${capital} ${sessions}x${minutes}m`);
    try {
      await syncLiveLevelIfNeeded(run_mode);
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id,
          capital,
          sessions,
          minutes,
          run_mode,
          accept_real: $("acceptReal").checked,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        let msg = res.statusText;
        if (typeof d === "string") msg = d;
        else if (Array.isArray(d))
          msg = d.map((x) => x.msg || JSON.stringify(x)).join("; ");
        else if (d && typeof d === "object") msg = JSON.stringify(d);
        throw new Error(msg);
      }
      currentRunId = data.run_id;
      applySnapshot(data);
      connectStream(currentRunId);
      await loadHealth();
    } catch (e) {
      appendLog("ERROR " + e.message);
      $("btnRun").disabled = false;
    }
  });

  $("btnStop").addEventListener("click", async () => {
    let rid = currentRunId;
    if (!rid) {
      const data = await fetch("/api/runs").then((r) => r.json());
      const active = (data.runs || []).find((x) => x.status === "running");
      rid = active?.run_id;
    }
    if (!rid) {
      appendLog("No hay run activo que parar.");
      return;
    }
    await fetch(`/api/runs/${rid}/stop`, { method: "POST" });
    appendLog("→ stop " + rid);
    $("btnRun").disabled = false;
    $("btnStop").disabled = true;
    $("pill-run").textContent = "STOPPED";
  });

  async function resumeActiveRun() {
    try {
      const data = await fetch("/api/runs").then((r) => r.json());
      const active = (data.runs || []).find((x) => x.status === "running");
      if (!active) return;
      currentRunId = active.run_id;
      appendLog(`↻ Reconectado a run activo ${active.run_id} (${active.mode})`);
      applySnapshot(active);
      connectStream(currentRunId);
      $("btnRun").disabled = true;
      $("btnStop").disabled = false;
    } catch (e) {
      appendLog("resume: " + e.message);
    }
  }

  Promise.all([loadHealth(), loadStrategies(), resumeActiveRun()]).catch((e) =>
    appendLog(String(e))
  );
})();
