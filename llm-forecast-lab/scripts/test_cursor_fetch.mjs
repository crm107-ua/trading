import Database from "better-sqlite3";

const db = new Database("data/lab.sqlite", { readonly: true });
const cursor = db.prepare("select v from meta where k='gamma_keyset_cursor'").get()?.v;
const count = db.prepare("select count(*) n from gamma_markets_raw").get();
db.close();

const url =
  `https://gamma-api.polymarket.com/markets/keyset?closed=true&limit=100&order=end_date&ascending=true` +
  `&end_date_min=2024-01-01&end_date_max=2026-12-31&after_cursor=${encodeURIComponent(String(cursor ?? ""))}`;

const t0 = Date.now();
const res = await fetch(url);
console.log("status", res.status, "ms", Date.now() - t0);
const body = await res.json();
console.log("markets", body.markets?.length, "next_cursor", Boolean(body.next_cursor));
