import { z } from "zod";

export const ForecastOutputSchema = z.object({
  p: z.number().min(0).max(1),
  key_factors: z.array(z.string()).max(20),
  base_rate_considered: z.string().min(1),
  confidence_note: z.string().min(1)
});
export type ForecastOutput = z.infer<typeof ForecastOutputSchema>;

