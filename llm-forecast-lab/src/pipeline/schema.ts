import { z } from "zod";

export const ForecastOutputSchema = z.object({
  p: z.number().min(0).max(1),
  key_factors: z.array(z.string()).max(20),
  base_rate_considered: z.string().min(1),
  confidence_note: z.string().min(1)
});
export type ForecastOutput = z.infer<typeof ForecastOutputSchema>;

/** Tolerates markdown fences and leading prose from LLM outputs. */
export function parseForecastOutput(text: string): ForecastOutput | null {
  const candidates = [text.trim()];
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced?.[1]) candidates.push(fenced[1].trim());
  const brace = text.match(/\{[\s\S]*\}/);
  if (brace?.[0]) candidates.push(brace[0]);

  for (const c of candidates) {
    try {
      const parsed = ForecastOutputSchema.safeParse(JSON.parse(c));
      if (parsed.success) return parsed.data;
    } catch {
      // try next candidate
    }
  }
  return null;
}

