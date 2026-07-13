import fs from "node:fs";
import path from "node:path";
import type Database from "better-sqlite3";
import { hashPrompt } from "../cache.js";
import { LlmClient } from "../client.js";
import { ForecastOutputSchema } from "../schema.js";
import { loadModelsConfig } from "../../config.js";
import { loadEvalFrozen } from "../../config.js";
import { isEligibleForModel } from "../../integrity/leakage.js";

function readPromptTemplate(): string {
  const p = path.join(process.cwd(), "src", "pipeline", "forecasters", "prompts", "naive.txt");
  return fs.readFileSync(p, "utf-8");
}

function fillTemplate(tpl: string, vars: Record<string, string>): string {
  let out = tpl;
  for (const [k, v] of Object.entries(vars)) {
    out = out.replaceAll(`{{${k}}}`, v);
  }
  return out;
}

export async function runNaiveForecast(args: {
  db: Database.Database;
  client: LlmClient;
  modelId: string;
  provider: string;
  pipeline: "naive";
  mode: "fixtures" | "live";
}): Promise<{ forecasts: number; failed: number; cacheHitRate: number }> {
  const tpl = readPromptTemplate();
  const cfg = loadModelsConfig("./config");
  const evalFrozen = loadEvalFrozen("./config");
  const model = cfg.models.find((m) => m.id === args.modelId);
  if (!model) throw new Error(`Unknown modelId in config: ${args.modelId}`);

  const hasSample = (
    args.db.prepare("select count(*) as n from run_questions").get() as { n: number }
  ).n;

  const rows = args.db
    .prepare(
      hasSample
        ? `
      select q.id as question_id, q.question_text, q.description, q.resolution_date, q.resolved_outcome,
             ms.horizon_hours, ms.snapshot_ts, ms.market_mid
      from questions q
      join run_questions rq on rq.question_id = q.id
      join market_snapshots ms on ms.question_id = q.id
      order by q.resolution_date asc
    `
        : `
      select q.id as question_id, q.question_text, q.description, q.resolution_date, q.resolved_outcome,
             ms.horizon_hours, ms.snapshot_ts, ms.market_mid
      from questions q
      join market_snapshots ms on ms.question_id = q.id
      order by q.resolution_date asc
    `
    )
    .all() as Array<{
    question_id: string;
    question_text: string;
    description: string | null;
    resolution_date: string;
    resolved_outcome: 0 | 1;
    horizon_hours: number;
    snapshot_ts: string;
    market_mid: number;
  }>;

  const eligibleRows = rows.filter((r) => {
    const el = isEligibleForModel({
      resolutionDateIso: r.resolution_date,
      modelTrainingCutoff: model.trainingCutoff,
      safetyMarginDays: evalFrozen.protocol.integrity.safetyMarginDays
    });
    return el.eligible;
  });

  const ins = args.db.prepare(`
    insert into forecasts (
      id, question_id, pipeline, model_id, provider, horizon_hours, forecast_ts,
      prompt_hash, cache_key, retrieval,
      p, key_factors_json, base_rate_considered, confidence_note,
      forecast_failed, raw_response_json, created_at
    )
    values (
      @id, @question_id, @pipeline, @model_id, @provider, @horizon_hours, @forecast_ts,
      @prompt_hash, @cache_key, @retrieval,
      @p, @key_factors_json, @base_rate_considered, @confidence_note,
      @forecast_failed, @raw_response_json, @created_at
    )
    on conflict(id) do nothing
  `);

  let ok = 0;
  let failed = 0;
  let cacheHits = 0;

  for (const r of eligibleRows) {
    const prompt = fillTemplate(tpl, {
      QUESTION_TEXT: r.question_text,
      DESCRIPTION: r.description ?? "",
      SNAPSHOT_TS: r.snapshot_ts,
      MARKET_MID: String(r.market_mid)
    });
    const promptHash = hashPrompt(prompt);
    const cacheKey = `${args.modelId}:${promptHash}`;
    const forecastTs = r.snapshot_ts;

    let p: number | null = null;
    let keyFactorsJson: string | null = null;
    let baseRate: string | null = null;
    let conf: string | null = null;
    let forecastFailed = 0;
    let rawResp: string | null = null;

    try {
      const res = await args.client.complete({
        provider: args.provider,
        model: args.modelId,
        prompt,
        temperature: 0
      });
      if (res.cacheHit) cacheHits += 1;
      rawResp = JSON.stringify({ text: res.text });

      // parse: one retry repair if needed
      const parsed1 = ForecastOutputSchema.safeParse(JSON.parse(res.text));
      let parsed = parsed1.success ? parsed1.data : null;
      if (!parsed) {
        const repairPrompt =
          "Your previous answer did not match the required JSON schema. " +
          "Return ONLY valid JSON for: {p, key_factors, base_rate_considered, confidence_note}. " +
          "Do not include any other text.\n\nOriginal:\n" +
          res.text;
        const rep = await args.client.complete({
          provider: args.provider,
          model: args.modelId,
          prompt: repairPrompt,
          temperature: 0
        });
        if (rep.cacheHit) cacheHits += 1;
        rawResp = JSON.stringify({ text: res.text, repair: rep.text });
        const parsed2 = ForecastOutputSchema.safeParse(JSON.parse(rep.text));
        if (parsed2.success) parsed = parsed2.data;
      }

      if (!parsed) throw new Error("forecast_parse_failed");

      p = parsed.p;
      keyFactorsJson = JSON.stringify(parsed.key_factors);
      baseRate = parsed.base_rate_considered;
      conf = parsed.confidence_note;
    } catch {
      forecastFailed = 1;
    }

    const id = `${r.question_id}:${r.horizon_hours}:${args.pipeline}:${args.modelId}`;
    ins.run({
      id,
      question_id: r.question_id,
      pipeline: args.pipeline,
      model_id: args.modelId,
      provider: args.provider,
      horizon_hours: r.horizon_hours,
      forecast_ts: forecastTs,
      prompt_hash: promptHash,
      cache_key: cacheKey,
      retrieval: "none",
      p,
      key_factors_json: keyFactorsJson,
      base_rate_considered: baseRate,
      confidence_note: conf,
      forecast_failed: forecastFailed,
      raw_response_json: rawResp,
      created_at: new Date().toISOString()
    });
    if (forecastFailed) failed += 1;
    else ok += 1;
  }

  const total = ok + failed;
  return {
    forecasts: total,
    failed,
    cacheHitRate: total === 0 ? 0 : cacheHits / total
  };
}

