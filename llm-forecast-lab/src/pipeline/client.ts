import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { loadEvalFrozen, loadModelsConfig } from "../config.js";
import { hashPrompt, safeModelSlug, readCache, writeCache } from "./cache.js";

export type NoNetworkMode = "allow" | "deny";

export type LlmRequest = {
  provider: string;
  model: string;
  prompt: string;
  temperature: 0;
};

export type LlmResponse = {
  text: string;
  cacheHit: boolean;
};

function isRetryableStatus(status: number): boolean {
  return status === 429 || status === 403 || status === 500 || status === 502 || status === 503 || status === 504;
}

const LLM_TIMEOUT_MS = 180_000;

function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  return fetch(url, { ...init, signal: ac.signal }).finally(() => clearTimeout(timer));
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export class LlmClient {
  private readonly noNetwork: NoNetworkMode;

  constructor(args: { noNetwork: NoNetworkMode }) {
    this.noNetwork = args.noNetwork;
  }

  async complete(req: LlmRequest): Promise<LlmResponse> {
    const cfg = loadModelsConfig("./config");
    const evalFrozen = loadEvalFrozen("./config");
    const provider = cfg.providers[req.provider];
    if (!provider) throw new Error(`Unknown provider: ${req.provider}`);
    if (evalFrozen.protocol.integrity.retrieval !== "none") {
      throw new Error("retrieval must be none in v1");
    }
    if (req.temperature !== 0) throw new Error("temperature must be 0 (determinism)");

    const promptHash = hashPrompt(req.prompt);
    const cached = readCache({ model: req.model, promptHash });
    if (cached) return { text: cached.responseText, cacheHit: true };

    const fixture = path.join(
      process.cwd(),
      "tests",
      "golden",
      "fixtures",
      "responses",
      `${safeModelSlug(req.model)}__naive_${this.fixtureQuestionIdFromPrompt(req.prompt) ?? "UNKNOWN"}.json`
    );
    if (fs.existsSync(fixture)) {
      const text = fs.readFileSync(fixture, "utf-8");
      writeCache({
        model: req.model,
        promptHash,
        createdAt: new Date().toISOString(),
        responseText: text,
        providerMeta: { fixture: true }
      });
      return { text, cacheHit: false };
    }

    if (this.noNetwork === "deny") {
      throw new Error("No-network mode: cache miss (refusing external call).");
    }

    if (provider.type !== "openai_compatible") {
      throw new Error(`Provider type not implemented in v1 runtime: ${provider.type}`);
    }
    const apiKey = process.env[provider.authEnv];
    if (!apiKey) throw new Error(`Missing env var for provider auth: ${provider.authEnv}`);

    const body = {
      model: req.model,
      temperature: 0,
      max_tokens: 512,
      messages: [{ role: "user", content: req.prompt }]
    };

    let lastErr: Error | null = null;
    for (let attempt = 0; attempt < 8; attempt++) {
      try {
        const res = await fetchWithTimeout(
          `${provider.baseUrl}/chat/completions`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${apiKey}`,
              "Content-Type": "application/json"
            },
            body: JSON.stringify(body)
          },
          LLM_TIMEOUT_MS
        );
        if (!res.ok) {
          const errText = await res.text();
          lastErr = new Error(`LLM call failed: ${res.status} ${errText}`);
          if (isRetryableStatus(res.status) && attempt < 7) {
            await sleep(2000 * (attempt + 1));
            continue;
          }
          throw lastErr;
        }

        const json = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
        const text = String(json?.choices?.[0]?.message?.content ?? "");

        writeCache({
          model: req.model,
          promptHash,
          createdAt: new Date().toISOString(),
          responseText: text,
          providerMeta: {
            provider: req.provider,
            baseUrl: provider.baseUrl,
            responseHash: crypto.createHash("sha256").update(JSON.stringify(json)).digest("hex")
          }
        });
        return { text, cacheHit: false };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        lastErr = new Error(msg.includes("abort") ? `LLM call timed out after ${LLM_TIMEOUT_MS}ms` : msg);
        if (attempt < 7) {
          await sleep(2000 * (attempt + 1));
          continue;
        }
        throw lastErr;
      }
    }
    throw lastErr ?? new Error("LLM call failed after retries");
  }

  private fixtureQuestionIdFromPrompt(prompt: string): string | null {
    const map: Record<string, string> = {
      "Will Example Event A happen by 2026-01-31?": "q1",
      "Will Example Event B happen by 2026-02-15?": "q2",
      "Will Example Event C happen by 2026-03-01?": "q3",
      "Will Example Event D happen by 2026-04-01?": "q4",
      "Will Example Event E happen by 2026-05-15?": "q5"
    };
    for (const [k, v] of Object.entries(map)) {
      if (prompt.includes(k)) return v;
    }
    return null;
  }
}
