import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export type CacheKey = {
  model: string;
  promptHash: string;
};

export type CachedResponse = {
  model: string;
  promptHash: string;
  createdAt: string;
  responseText: string;
  providerMeta?: Record<string, unknown>;
};

export function hashPrompt(text: string): string {
  return crypto.createHash("sha256").update(text).digest("hex");
}

export function cacheDir(): string {
  return path.join(process.cwd(), "data", "responses");
}

export function cachePath(key: CacheKey): string {
  const safeModel = key.model.replace(/[^a-zA-Z0-9._-]/g, "_");
  return path.join(cacheDir(), `${safeModel}__${key.promptHash}.json`);
}

export function readCache(key: CacheKey): CachedResponse | null {
  const p = cachePath(key);
  if (!fs.existsSync(p)) return null;
  const raw = JSON.parse(fs.readFileSync(p, "utf-8")) as CachedResponse;
  if (raw.model !== key.model || raw.promptHash !== key.promptHash) return null;
  return raw;
}

export function writeCache(resp: CachedResponse): void {
  fs.mkdirSync(cacheDir(), { recursive: true });
  const p = cachePath({ model: resp.model, promptHash: resp.promptHash });
  fs.writeFileSync(p, JSON.stringify(resp, null, 2) + "\n", "utf-8");
}

