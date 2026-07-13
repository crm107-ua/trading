import { z } from "zod";

export const ResolutionSchema = z.object({
  resolvedOutcome: z.enum(["YES", "NO"]),
  resolutionDate: z.string()
});
export type Resolution = z.infer<typeof ResolutionSchema>;

export const PricePointSchema = z.object({
  ts: z.string(),
  mid: z.number().min(0).max(1)
});
export type PricePoint = z.infer<typeof PricePointSchema>;

export const QuestionSchema = z.object({
  id: z.string().min(1),
  source: z.literal("polymarket"),
  questionText: z.string().min(1),
  description: z.string().optional(),
  category: z.string().optional(),
  resolution: ResolutionSchema,
  ambiguousResolution: z.boolean(),
  liquidityProxy: z.number().nonnegative().default(0),
  // For ingestion we store full history; later we extract horizons.
  priceHistory: z.array(PricePointSchema)
});
export type Question = z.infer<typeof QuestionSchema>;

export type IngestReject = { reason: string; id?: string };

