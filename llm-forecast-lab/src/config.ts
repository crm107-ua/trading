import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { z } from "zod";

export const ModelsConfigSchema = z.object({
  providers: z.record(
    z.string(),
    z.object({
      type: z.enum(["openai_compatible", "anthropic"]),
      baseUrl: z.string().url(),
      authEnv: z.string().min(1)
    })
  ),
  models: z.array(
    z.object({
      id: z.string().min(1),
      provider: z.string().min(1),
      trainingCutoff: z.string().regex(/^\d{4}-\d{2}-\d{2}$/)
    })
  )
});
export type ModelsConfig = z.infer<typeof ModelsConfigSchema>;

export const EvalFrozenSchema = z.object({
  frozen: z.literal(true),
  frozenAt: z.string(),
  freezeHash: z.string().min(1),
  protocol: z.object({
    horizonsHoursBeforeResolution: z.array(z.number().int().positive()),
    selection: z.object({
      minLiquidityProxy: z.number().nonnegative(),
      includeCategories: z.array(z.string()),
      excludeCategories: z.array(z.string()),
      dateRange: z.object({
        resolutionFrom: z.string(),
        resolutionTo: z.string()
      }),
      minMarketDurationDays: z.number().int().positive(),
      excludeAmbiguousResolution: z.boolean()
    }),
    temporalSplit: z.object({
      heldoutLastPctByResolutionDate: z.number().min(0).max(0.99)
    }),
    integrity: z.object({
      safetyMarginDays: z.number().int().nonnegative(),
      retrieval: z.literal("none"),
      canary: z.object({
        enabled: z.boolean(),
        canaryCountPerModel: z.number().int().nonnegative(),
        minLagDays: z.number().int().nonnegative(),
        maxLagDays: z.number().int().nonnegative(),
        brierSuspiciousThreshold: z.number().min(0).max(1),
        minEligibleHeldoutQuestions: z.number().int().nonnegative()
      }),
      canarySupplement: z.object({
        enabled: z.boolean(),
        resolutionFrom: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        resolutionTo: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        targetCount: z.number().int().positive()
      }),
      temporalCanary: z.object({
        enabled: z.boolean(),
        heldInFrom: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        heldInTo: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        skillSuspiciousThreshold: z.number(),
        heldoutSkillPoorThreshold: z.number()
      }),
      maxForecastFailedRate: z.number().min(0).max(1),
      maxIngestRejectRate: z.number().min(0).max(1)
    }),
    universe: z.object({
      mode: z.enum(["keyset_full", "offset_truncated"]),
      ingestAsOf: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
      documentedTruncation: z.boolean()
    }),
    runSampling: z.object({
      enabled: z.boolean(),
      seed: z.number().int(),
      targetQuestions: z.number().int().positive(),
      requireModelIntersection: z.boolean(),
      strata: z.object({
        resolutionQuarter: z.object({ enabled: z.boolean(), proportional: z.boolean() }),
        category: z.object({
          enabled: z.boolean(),
          proportional: z.boolean(),
          unknownBucket: z.string().min(1)
        })
      }),
      minHeldoutQuestionsAfterSplit: z.number().int().positive()
    }),
    ensemble: z.object({
      enabled: z.boolean(),
      modelsN: z.number().int().positive(),
      promptVariantsM: z.number().int().positive(),
      trimPct: z.number().min(0).max(0.49)
    }),
    verdict: z.object({
      matchSkillAbs: z.number().nonnegative(),
      bootstrap: z.object({
        iterations: z.number().int().positive(),
        seed: z.number().int(),
        ci: z.number().min(0.5).max(0.999)
      })
    })
  })
});
export type EvalFrozen = z.infer<typeof EvalFrozenSchema>;

export function repoRoot(): string {
  return path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
}

export function readJsonFile<T>(filePath: string, schema: z.ZodType<T>): T {
  const raw = fs.readFileSync(filePath, "utf-8");
  const json = JSON.parse(raw) as unknown;
  return schema.parse(json);
}

export function sha256Hex(input: string): string {
  return crypto.createHash("sha256").update(input).digest("hex");
}

export function canonicalJson(obj: unknown): string {
  // Stable stringify for hashing: sort keys recursively.
  const norm = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(norm);
    if (v && typeof v === "object") {
      const o = v as Record<string, unknown>;
      const keys = Object.keys(o).sort();
      const out: Record<string, unknown> = {};
      for (const k of keys) out[k] = norm(o[k]);
      return out;
    }
    return v;
  };
  return JSON.stringify(norm(obj));
}

export function computeFreezeHash(evalFrozen: EvalFrozen): string {
  // Hash everything except freezeHash itself (so it can verify itself).
  const { freezeHash: _ignore, ...rest } = evalFrozen;
  return sha256Hex(canonicalJson(rest));
}

export function loadEvalFrozen(configDir: string): EvalFrozen {
  const p = path.join(configDir, "eval_frozen.json");
  const raw = fs.readFileSync(p, "utf-8");
  const parsed = EvalFrozenSchema.parse(JSON.parse(raw));
  const computed = computeFreezeHash(parsed);
  if (parsed.freezeHash !== computed) {
    throw new Error(
      `Frozen config hash mismatch. expected=${parsed.freezeHash} computed=${computed}. Refusing to run.`
    );
  }
  if (parsed.freezeHash === "UNFROZEN_PLACEHOLDER") {
    throw new Error("eval_frozen.json is not frozen (placeholder hash). Refusing to run.");
  }
  return parsed;
}

export function loadModelsConfig(configDir: string): ModelsConfig {
  return readJsonFile(path.join(configDir, "models.json"), ModelsConfigSchema);
}

