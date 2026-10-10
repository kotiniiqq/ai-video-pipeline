/** One-time setup of the local stack after `docker compose up -d --build`:
 *  n8n owner account and API key, the Postgres credential (fixed id from environments.json),
 *  then build, deploy and publish every workflow with the kit.
 *
 *   npm run setup
 *
 *  The owner account is for this local stack only; change it before exposing n8n anywhere.
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { build, loadEnvironments } from '../kit/build.ts';
import { ROOT } from '../kit/code.ts';
import { deploy } from '../kit/deploy.ts';
import { N8nApi } from '../kit/n8n-api.ts';

const BASE = process.env.N8N_URL ?? 'http://localhost:5678';
const OWNER = {
  email: process.env.N8N_OWNER_EMAIL ?? 'owner@example.com',
  firstName: 'Pipeline',
  lastName: 'Owner',
  password: process.env.N8N_OWNER_PASSWORD ?? 'Pipeline-local-1',
};
const json = { 'content-type': 'application/json' };
const STATE = path.join(ROOT, '.n8n-kit');

async function waitForN8n(timeoutMs = 180_000) {
  const until = Date.now() + timeoutMs;
  for (;;) {
    try {
      if ((await fetch(`${BASE}/healthz/readiness`)).ok) return;
    } catch { /* not up yet */ }
    if (Date.now() > until) throw new Error(`n8n did not become ready on ${BASE}/healthz/readiness`);
    await new Promise((r) => setTimeout(r, 2000));
  }
}

async function call(p: string, init: RequestInit = {}) {
  const r = await fetch(`${BASE}${p}`, init);
  if (!r.ok) throw new Error(`${init.method ?? 'GET'} ${p} -> ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r;
}

async function apiKey(): Promise<string> {
  const keyFile = path.join(STATE, 'compose.key');
  if (fs.existsSync(keyFile)) {
    const key = fs.readFileSync(keyFile, 'utf8').trim();
    if ((await fetch(`${BASE}/api/v1/workflows?limit=1`, { headers: { 'X-N8N-API-KEY': key } })).ok) return key;
  }
  const setup = await fetch(`${BASE}/rest/owner/setup`, { method: 'POST', headers: json, body: JSON.stringify(OWNER) });
  if (!setup.ok && setup.status !== 400) throw new Error(`owner setup -> ${setup.status}`); // 400: owner exists
  const login = await call('/rest/login', { method: 'POST', headers: json, body: JSON.stringify({ emailOrLdapLoginId: OWNER.email, password: OWNER.password }) });
  const headers = { ...json, cookie: login.headers.getSetCookie().map((c) => c.split(';')[0]).join('; '), 'browser-id': 'pipeline-setup' };
  const scopes = (await (await call('/rest/api-keys/scopes', { headers })).json()).data;
  const res = await call('/rest/api-keys', { method: 'POST', headers, body: JSON.stringify({ label: `setup-${Date.now()}`, scopes, expiresAt: null }) });
  const key = (await res.json()).data.rawApiKey as string;
  fs.mkdirSync(STATE, { recursive: true });
  fs.writeFileSync(keyFile, key);
  return key;
}

function importCredential() {
  const id = loadEnvironments().compose.credentials['pipeline-db'];
  const cred = [{
    id, name: 'pipeline-db', type: 'postgres',
    data: { host: 'postgres', port: 5432, database: 'pipeline', user: 'pipeline',
            password: process.env.PIPELINE_DB_PASSWORD ?? 'pipeline-local', ssl: 'disable' },
  }];
  execFileSync('docker', ['compose', 'exec', '-T', 'n8n', 'sh', '-c', 'cat > /tmp/creds.json && n8n import:credentials --input=/tmp/creds.json && rm /tmp/creds.json'],
    { cwd: ROOT, input: JSON.stringify(cred), stdio: ['pipe', 'ignore', 'inherit'] });
}

await waitForN8n();
const key = await apiKey();
importCredential();
const steps = await deploy(await build('compose'), {
  env: 'compose', api: new N8nApi(BASE, key), stateDir: STATE, backupDir: path.join(ROOT, 'backups'),
  log: (l) => console.log(l),
});
console.log(`deployed: ${steps.map((s) => `${s.workflow} ${s.action}`).join(', ')}`);
console.log(`\nn8n:    ${BASE}  (${OWNER.email} / ${OWNER.password})`);
console.log(`create: curl -X POST ${BASE}/webhook/video -H 'content-type: application/json' -d '{"topic":"The first transatlantic telegraph cable"}'`);
console.log(`status: curl '${BASE}/webhook/video-status?id=1'`);
