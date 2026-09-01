// ACI JavaScript SDK (fetch-based). Works in the browser and Node 18+.
// Same open HTTP interface as every other ACI client.
//   import { ACIClient } from "./aci.js";
//   const aci = new ACIClient("http://127.0.0.1:7077", "optional-api-key");
//   await aci.monadise("My accountant is Sarah Chen.");
//   const hits = await aci.recall("accountant");
export class ACIClient {
  constructor(baseUrl = "http://127.0.0.1:7077", apiKey = null) {
    this.base = baseUrl.replace(/\/$/, "");
    this.key = apiKey;
  }
  async _req(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (this.key) headers["X-API-Key"] = this.key;
    const res = await fetch(this.base + path, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
    });
    return res.json();
  }
  health() { return this._req("GET", "/health"); }
  compress() { return this._req("GET", "/compress"); }
  monadise(content, opts = {}) { return this._req("POST", "/monadise", { content, ...opts }); }
  recall(query, k = 5, observer = null) { return this._req("POST", "/recall", { query, k, observer }); }
  validate(statement, opts = {}) { return this._req("POST", "/validate", { statement, ...opts }); }
  relate(source_id, target_id, type = "ASSOCIATIVE") { return this._req("POST", "/relate", { source_id, target_id, type }); }
  route(query) { return this._req("POST", "/route", { query }); }
  monads(limit = 50) { return this._req("GET", `/monads?limit=${limit}`); }
  forget(id) { return this._req("POST", "/forget", { id }); }
}
