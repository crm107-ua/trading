import { Command } from "commander";
import fs from "node:fs";
import path from "node:path";
import { loadEvalFrozen, loadModelsConfig } from "./config.js";
import { loadDotEnv } from "./env.js";
import { openDb } from "./db.js";
import { computeUniverseComposition, passesSelectionFilters } from "./ingest/filters.js";
import { buildCompositionAnnotations } from "./ingest/composition_notes.js";
import { loadGammaMarketsFromDb, readKeysetProgress } from "./ingest/gamma_keyset_ingest.js";
import { ingestPolymarket } from "./ingest/ingest.js";
import { runViabilityCheck } from "./ingest/viability.js";
import { LlmClient } from "./pipeline/client.js";
import { DEFAULT_NIM_MODEL, DEFAULT_NIM_PROVIDER, DEFAULT_PIPELINE } from "./defaults.js";
import { runNaiveForecast } from "./pipeline/forecasters/naive.js";
import { canarySupplementStatus, ingestCanarySupplement } from "./ingest/canary_ingest.js";
import { computeSampleReport, intersectionEligibleQuestions } from "./selection/sample.js";
import { scoreForecasts } from "./eval/score_run.js";
import { generateReport } from "./eval/report.js";
import { runSimPaper } from "./eval/sim_paper.js";
import { runEvalDayD } from "./eval/eval_day_d.js";
import { runSimPaperGrid } from "./eval/sim_grid.js";

loadDotEnv();

const program = new Command();

program.name("llm-forecast-lab").description("LLM Forecast Lab (evaluation only, no PnL)").version("0.1.0");

program
  .command("ingest")
  .requiredOption("--source <source>", "polymarket")
  .requiredOption("--mode <mode>", "fixtures|live")
  .action(async (opts) => {
    if (opts.source !== "polymarket") throw new Error("Only polymarket supported in v1");
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const rep = await ingestPolymarket(db, { mode });
    db.prepare("insert into meta(k,v) values('ingested',@v) on conflict(k) do update set v=excluded.v").run({
      v: String(rep.ingested)
    });
    db.prepare("insert into meta(k,v) values('ingest_rejects',@v) on conflict(k) do update set v=excluded.v").run({
      v: String(rep.horizonSnapshotRejects + rep.rejects)
    });
    console.log(JSON.stringify(rep, null, 2));
  });

program
  .command("ingest-progress")
  .description("Fast keyset ingest progress (% by monthly chunks; no cascade).")
  .action(() => {
    const evalFrozen = loadEvalFrozen("./config");
    const db = openDb("live");
    const from = evalFrozen.protocol.selection.dateRange.resolutionFrom;
    const to = evalFrozen.protocol.selection.dateRange.resolutionTo;
    const p = readKeysetProgress(db, from, to);
    const clobNote = p.complete
      ? "keyset done — if ingest still running, CLOB phase may follow"
      : "CLOB + sampling after keyset reaches 100%";
    console.log(
      JSON.stringify(
        {
          keysetPct: p.keysetPct,
          chunks: `${p.chunksDone}/${p.chunksTotal}`,
          activeChunk: p.activeChunk,
          activeChunkPages: p.activeChunkPages,
          activeChunkPagesEst: p.activeChunkPagesEst,
          pages: p.pages,
          unique: p.unique,
          complete: p.complete,
          note: `keysetPct = months completed + intra-chunk pages/estimate. ${clobNote}.`
        },
        null,
        2
      )
    );
  });

program
  .command("ingest-cascade")
  .description("Filter cascade from gamma_markets_raw (partial or complete keyset).")
  .action(() => {
    const evalFrozen = loadEvalFrozen("./config");
    const modelsCfg = loadModelsConfig("./config");
    const db = openDb("live");

    const meta = Object.fromEntries(
      (db.prepare("select k, v from meta where k like 'gamma_keyset%'").all() as Array<{ k: string; v: string }>).map(
        (r) => [r.k, r.v]
      )
    );

    const markets = loadGammaMarketsFromDb(db);
    const composition = computeUniverseComposition(markets, evalFrozen);

    const eligiblePool = markets
      .filter((m) => passesSelectionFilters(m, evalFrozen))
      .map((m) => ({
        id: m.slug ?? m.id,
        category: m.category ?? null,
        resolution_date: String(m.endDate),
        liquidity_proxy: Number(m.liquidityNum ?? m.volumeNum ?? 0)
      }));

    const { eligible, eligibleByModel } = intersectionEligibleQuestions(eligiblePool, modelsCfg, evalFrozen);
    const sample = computeSampleReport({ questions: eligiblePool, evalFrozen, modelsCfg });

    const bySlug = new Map(markets.map((m) => [m.slug ?? m.id, m]));
    const compositionAnnotations = buildCompositionAnnotations(
      eligible.map((e) => ({
        slug: e.id,
        question: bySlug.get(e.id)?.question ?? e.id,
        resolution_date: e.resolution_date
      }))
    );

    const raw = composition.raw;
    const pct = (n: number, base: number) => (base > 0 ? Number(((n / base) * 100).toFixed(2)) : 0);
    const step = (n: number, baseRaw: number, prev?: number) => ({
      n,
      pctOfRaw: pct(n, baseRaw),
      ...(prev !== undefined ? { pctOfPrev: pct(n, prev) } : {})
    });

    const cascade = {
      raw: step(raw, raw),
      afterDateRange: step(composition.afterDateRange, raw, raw),
      afterBinaryYesNo: step(composition.afterBinaryYesNo, raw, composition.afterDateRange),
      afterDuration: step(composition.afterDuration, raw, composition.afterBinaryYesNo),
      afterLiquidity: step(composition.afterLiquidity, raw, composition.afterDuration),
      afterDispute: step(composition.afterDispute, raw, composition.afterLiquidity),
      afterAllSelection: step(composition.afterAllSelection, raw, composition.afterDispute),
      binaryToDurationRatio:
        composition.afterBinaryYesNo > 0
          ? Number((composition.afterDuration / composition.afterBinaryYesNo).toFixed(4))
          : 0
    };

    const topCats = Object.entries(composition.byCategory)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([cat, n]) => ({
        cat,
        n,
        pctOfEligible: composition.afterAllSelection > 0 ? pct(n, composition.afterAllSelection) : 0
      }));

    const heldoutOk =
      sample.expectedHeldoutQuestions >= evalFrozen.protocol.runSampling.minHeldoutQuestionsAfterSplit;
    const keysetOk = meta.gamma_keyset_complete === "true";

    const canaryStatus = canarySupplementStatus(db, evalFrozen);

    const dedup = db
      .prepare(
        `
      SELECT
        COUNT(*) AS total,
        COUNT(DISTINCT slug) AS distinct_slug,
        COUNT(DISTINCT market_id) AS distinct_market_id,
        COUNT(DISTINCT json_extract(payload_json,'$.id')) AS distinct_payload_id
      FROM gamma_markets_raw
    `
      )
      .get() as {
      total: number;
      distinct_slug: number;
      distinct_market_id: number;
      distinct_payload_id: number;
    };
    const dedupOk =
      dedup.total === dedup.distinct_slug &&
      dedup.total === dedup.distinct_market_id &&
      dedup.total === dedup.distinct_payload_id;

    console.log(
      JSON.stringify(
        {
          keyset: {
            pages: Number(meta.gamma_keyset_pages ?? 0),
            fetchedUnique: markets.length,
            complete: keysetOk,
            resumed: Number(meta.gamma_keyset_pages ?? 0) > 0 && !keysetOk
          },
          cascade,
          durationDays: {
            ...composition.durationDays,
            population: "afterDuration",
            minDaysFilter: evalFrozen.protocol.selection.minMarketDurationDays
          },
          byCategoryTop10: topCats,
          categoryConcentrationTop1Pct: topCats[0]?.pctOfEligible ?? 0,
          composition: compositionAnnotations,
          intersection: {
            eligibleByModel,
            intersectionEligible: step(eligible.length, raw, composition.afterAllSelection)
          },
          sampling: {
            seed: sample.seed,
            targetQuestions: sample.targetQuestions,
            selectedQuestions: sample.selectedQuestions,
            expectedHeldoutQuestions: sample.expectedHeldoutQuestions,
            minHeldoutRequired: evalFrozen.protocol.runSampling.minHeldoutQuestionsAfterSplit,
            heldoutOk
          },
          checks: {
            keysetComplete: keysetOk,
            heldoutAboveMin: heldoutOk,
            intersectionAboveTarget: eligible.length >= sample.targetQuestions,
            dedupSanity: dedupOk,
            canarySupplementOk: canaryStatus.ok
          },
          dedupSanity: {
            ...dedup,
            ok: dedupOk,
            note: "total must equal distinct slug, market_id, and payload id — else keyset cursor inflated duplicates"
          },
          canarySupplement: canaryStatus,
          readyForForecast:
            keysetOk && heldoutOk && eligible.length >= sample.targetQuestions && dedupOk && canaryStatus.ok
        },
        null,
        2
      )
    );
  });

program
  .command("viability")
  .description("Cheap live data viability check (Gamma + leakage filters).")
  .action(async () => {
    const rep = await runViabilityCheck();
    console.log(JSON.stringify(rep, null, 2));
  });

program
  .command("ingest-canaries")
  .description("Supplemental keyset pull for leakage canaries (canary_only; excluded from eval sample).")
  .action(async () => {
    const evalFrozen = loadEvalFrozen("./config");
    const db = openDb("live");
    const rep = await ingestCanarySupplement(db, evalFrozen);
    console.log(JSON.stringify(rep, null, 2));
  });

program
  .command("forecast")
  .requiredOption("--pipeline <pipeline>", "naive")
  .requiredOption("--mode <mode>", "fixtures|live")
  .option("--model <model>", "model id", DEFAULT_NIM_MODEL)
  .option("--provider <provider>", "provider name", DEFAULT_NIM_PROVIDER)
  .option("--no-network", "deny network; require cache/fixtures", false)
  .action(async (opts) => {
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const client = new LlmClient({ noNetwork: opts.noNetwork ? "deny" : "allow" });
    if (opts.pipeline !== "naive") throw new Error("Only naive supported in v1");
    const rep = await runNaiveForecast({
      db,
      client,
      modelId: opts.model,
      provider: opts.provider,
      pipeline: "naive",
      mode
    });
    db.prepare("insert into meta(k,v) values('cache_hit_rate',@v) on conflict(k) do update set v=excluded.v").run({
      v: String(rep.cacheHitRate)
    });
    console.log(JSON.stringify(rep, null, 2));
  });

program
  .command("score")
  .requiredOption("--mode <mode>", "fixtures|live")
  .action((opts) => {
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const rep = scoreForecasts(db);
    console.log(JSON.stringify(rep, null, 2));
  });

program
  .command("sim-paper")
  .description("Exploratory mid-only taker PnL on held-out (non-binding; does not affect eval verdict).")
  .requiredOption("--mode <mode>", "fixtures|live")
  .option("--pipeline <pipeline>", "pipeline name", DEFAULT_PIPELINE)
  .option("--out <path>", "write JSON to file")
  .action((opts) => {
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const rep = runSimPaper(db, { pipeline: opts.pipeline });
    const json = JSON.stringify(rep, null, 2) + "\n";
    if (opts.out) {
      const outPath = path.resolve(opts.out);
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      fs.writeFileSync(outPath, json);
    }
    console.log(json.trimEnd());
  });

program
  .command("sim-paper-grid")
  .description("Sweep minNetEdge values (exploratory calibration).")
  .requiredOption("--mode <mode>", "fixtures|live")
  .option("--pipeline <pipeline>", "pipeline name", DEFAULT_PIPELINE)
  .option("--from <n>", "min edge start", "0.01")
  .option("--to <n>", "min edge end", "0.10")
  .option("--step <n>", "step", "0.01")
  .option("--out <path>", "write JSON to file")
  .action((opts) => {
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const rep = runSimPaperGrid(db, {
      pipeline: opts.pipeline,
      from: Number(opts.from),
      to: Number(opts.to),
      step: Number(opts.step)
    });
    const json = JSON.stringify(rep, null, 2) + "\n";
    if (opts.out) {
      const outPath = path.resolve(opts.out);
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      fs.writeFileSync(outPath, json);
    }
    console.log(json.trimEnd());
  });

program
  .command("eval-day-d")
  .description("Day D bundle: score → report (writes output/<runId>/report.json).")
  .requiredOption("--mode <mode>", "fixtures|live")
  .option("--pipeline <pipeline>", "pipeline name", DEFAULT_PIPELINE)
  .action((opts) => {
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const bundle = runEvalDayD(db, { pipeline: opts.pipeline, mode });
    console.log(
      JSON.stringify(
        {
          outputDir: bundle.outputDir,
          score: bundle.score,
          verdict: bundle.report.verdict,
          reason: bundle.report.reason,
          skill: bundle.report.metrics.skill,
          heldoutQuestionsN: bundle.report.metrics.heldoutQuestionsN,
          auditRequired: bundle.report.integrity.auditRequired,
          hardIntegrityFailure: bundle.report.integrity.hardIntegrityFailure
        },
        null,
        2
      )
    );
  });

program
  .command("report")
  .requiredOption("--mode <mode>", "fixtures|live")
  .option("--pipeline <pipeline>", "pipeline name", DEFAULT_PIPELINE)
  .action((opts) => {
    const mode = opts.mode === "live" ? "live" : "fixtures";
    const db = openDb(mode);
    const rep = generateReport(db, { pipeline: opts.pipeline, mode });
    console.log(JSON.stringify(rep, null, 2));
  });

await program.parseAsync(process.argv);

