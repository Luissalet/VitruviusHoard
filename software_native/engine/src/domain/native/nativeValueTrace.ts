import { z } from "zod";
import { nativePcodeOperationSchema } from "./nativeValueFlow.js";

/** Work and output budgets for a static procedure-seeded dependency graph. */
export const nativeValueTraceInputSchema = z.strictObject({
  procedure: z.string().min(1),
  max_depth: z.number().int().min(0).default(Number.MAX_SAFE_INTEGER),
  max_functions: z.number().int().min(1).default(Number.MAX_SAFE_INTEGER),
  max_call_sites: z.number().int().min(1).default(Number.MAX_SAFE_INTEGER),
  max_nodes: z.number().int().min(1).default(Number.MAX_SAFE_INTEGER),
  max_edges: z.number().int().min(1).default(Number.MAX_SAFE_INTEGER),
  offset: z.number().int().min(0).default(0),
  limit: z.number().int().min(1).default(Number.MAX_SAFE_INTEGER),
});
/** Def-use observations and call relationships retain separate authority. */
export const nativeValueTraceSchema = z.strictObject({
  seed: z.string(),
  target_sha256: z.string(),
  nodes: z.array(
    z.strictObject({
      id: z.string(),
      procedure: z.string(),
      evidence_id: z.string(),
      kind: z.enum(["operation", "parameter"]),
      operation: nativePcodeOperationSchema.nullable(),
      parameter: z
        .strictObject({
          ordinal: z.number().int().nonnegative(),
          name: z.string(),
          data_type: z.string(),
        })
        .nullable(),
    }),
  ),
  edges: z.array(
    z.strictObject({
      source: z.string(),
      target: z.string(),
      input_index: z.number().int().nonnegative().nullable(),
      kind: z.enum([
        "def-use",
        "call",
        "parameter-use",
        "argument-binding",
        "return-binding",
      ]),
      status: z.enum(["derived", "direct", "resolved-indirect", "candidate"]),
      evidence_id: z.string(),
    }),
  ),
  procedures: z.array(
    z.strictObject({
      address: z.string(),
      depth: z.number().int().nonnegative(),
      evidence_id: z.string(),
      provider: z.string(),
      analysis_profile_digest: z.string().nullable(),
    }),
  ),
  unknowns: z.array(
    z.strictObject({
      procedure: z.string(),
      address: z.string().nullable(),
      reason: z.string(),
    }),
  ),
  total_nodes: z.number().int().nonnegative(),
  total_edges: z.number().int().nonnegative(),
  decompilations: z.number().int().nonnegative(),
  next_offset: z.number().int().nonnegative().nullable(),
  truncated: z.boolean(),
  limitations: z.array(z.string()),
});
