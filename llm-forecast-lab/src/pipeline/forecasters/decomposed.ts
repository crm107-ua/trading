import { ForecastOutput, ForecastOutputSchema } from "../schema.js";

/**
 * v1 placeholder: decomposed pipeline is defined, but implemented in v2.
 * We keep the module for layout parity and to prevent accidental PnL additions.
 */
export function decomposedNotImplemented(): ForecastOutput {
  return ForecastOutputSchema.parse({
    p: 0.5,
    key_factors: ["not_implemented_v1"],
    base_rate_considered: "not_implemented_v1",
    confidence_note: "not_implemented_v1"
  });
}

