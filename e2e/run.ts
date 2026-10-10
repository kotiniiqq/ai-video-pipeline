/** End-to-end run against the compose stack in demo mode (no keys, no network beyond localhost).
 *
 *   docker compose up -d --build && npm run setup && npm run e2e
 *
 * Asks for a video through the webhook, follows it through every stage, and checks the result:
 * final QC passed (length matches the narration, -14 LUFS, no black), 1280x720 with sound,
 * subtitles cover the narration, thumbnail exists, every shot finished, demo cost is zero.
 * With DEMO_FAULTS=1 (set for the worker too) some shots fail on purpose; the run must still finish,
 * with retried shots and at least one Ken Burns fallback.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';

const N8N = process.env.N8N_URL ?? 'http://localhost:5678';
const WORKER = process.env.WORKER_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = Number(process.env.E2E_TIMEOUT_MS ?? 15 * 60_000);

async function post(url: string, body: unknown) {
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}

function readInWorker(path: string): string {
  return execFileSync('docker', ['compose', 'exec', '-T', 'worker', 'cat', path], { encoding: 'utf8' });
}

// bad input is refused before anything is stored
const bad = await post(`${N8N}/webhook/video`, { topic: ' ' });
assert.equal(bad.status, 400, JSON.stringify(bad.body));
assert.equal((await fetch(`${N8N}/webhook/video-status?id=999999`)).status, 404);

const topic = 'The first transatlantic telegraph cable';
const created = await post(`${N8N}/webhook/video`, { topic });
assert.equal(created.status, 202, JSON.stringify(created.body));
const id = created.body.id as number;
console.log(`video ${id} queued: ${topic}`);

let status: Record<string, any> = {};
let last = '';
const started = Date.now();
while (Date.now() - started < TIMEOUT_MS) {
  status = await (await fetch(`${N8N}/webhook/video-status?id=${id}`)).json();
  const line = `${status.status}${status.status === 'production' ? ` ${status.shots_finished}/${status.shots_total}` : ''}`;
  if (line !== last) console.log(`${((Date.now() - started) / 1000).toFixed(0).padStart(4)}s  ${line}`);
  last = line;
  if (status.status === 'ready') break;
  if (status.status === 'failed') throw new Error(`video failed: ${status.last_error}`);
  await new Promise((r) => setTimeout(r, 5000));
}
assert.equal(status.status, 'ready', `not ready after ${TIMEOUT_MS / 60000} min: ${JSON.stringify(status)}`);

assert.equal(status.final_qc.status, 'PASS', JSON.stringify(status.final_qc));
assert.ok(Math.abs(status.final_qc.lufs + 14) <= 1, `loudness ${status.final_qc.lufs}`);
const probe = await post(`${WORKER}/probe`, { path: status.final_path });
assert.equal(probe.status, 200);
assert.deepEqual([probe.body.width, probe.body.height, probe.body.has_audio], [1280, 720, true]);
assert.ok(probe.body.duration > 60, `a 7-paragraph narration should last over a minute, got ${probe.body.duration}s`);

const srt = readInWorker(status.srt_path);
const cues = srt.trim().split(/\n\n+/);
assert.ok(cues.length >= 7, `expected subtitles, got ${cues.length} cues`);

const thumb = await post(`${WORKER}/qc/image`, { path: status.thumbnail_path });
assert.deepEqual([thumb.body.width, thumb.body.height], [1280, 720]);

assert.equal(status.shots_finished, status.shots_total);
assert.ok(status.shots_total >= 7);
assert.equal(status.cost_usd, 0);
if (process.env.DEMO_FAULTS) { // injected failures: retries and the fallback path must have run and recovered
  assert.ok(status.shots_retried >= 2, `expected retried shots, got ${status.shots_retried}`);
  assert.ok(status.shots_fallback >= 1, `expected a fallback shot, got ${status.shots_fallback}`);
}
assert.ok(status.title && status.description.includes('Sources:'), 'title and description');

console.log(`\nok: "${status.title}" — ${probe.body.duration}s, ${status.shots_total} shots (${status.shots_retried} retried, ${status.shots_fallback} fallback), `
  + `${cues.length} subtitle cues, ${status.final_qc.lufs} LUFS, in ${((Date.now() - started) / 1000).toFixed(0)}s`);
