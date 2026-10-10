import assert from 'node:assert/strict';
import { test } from 'node:test';

import assemblyPlan, { planSegments } from '../code/assembly-plan.ts';
import formatError from '../code/format-error.ts';
import pickTitles from '../code/pick-titles.ts';
import { afterJob, afterQc, afterStart, MAX_ATTEMPTS } from '../code/shot-step.ts';
import stageResult from '../code/stage-result.ts';
import validateIntake from '../code/validate-intake.ts';
import { checkScript } from '../code/validate-script.ts';
import { checkStoryboard } from '../code/validate-storyboard.ts';
import { timeline } from '../code/voice-timeline.ts';

const ctx = { now: '2026-10-11T10:00:00.000Z', node: () => [] };
const one = (json: Record<string, unknown>) => [{ json }];

// ---- intake ---------------------------------------------------------------------------------

test('intake cleans the topic and keeps it a plain string', () => {
  const [out] = validateIntake(one({ body: { topic: "  The cable\n\u0007 '; DROP TABLE videos; -- 🚢 ", notes: ' n ' } }), ctx);
  assert.equal(out.json.valid, true);
  assert.equal(out.json.topic, "The cable '; DROP TABLE videos; -- 🚢");
  assert.equal(out.json.notes, 'n');
});

test('intake rejects empty, too short and too long topics', () => {
  for (const topic of ['', '  ', 'ab', 'x'.repeat(201), 42]) {
    const [out] = validateIntake(one({ body: { topic } }), ctx);
    assert.equal(out.json.valid, false, String(topic));
    assert.match((out.json.errors as string[])[0], /topic/);
  }
});

test('intake caps notes', () => {
  const [out] = validateIntake(one({ body: { topic: 'Lighthouses', notes: 'n'.repeat(1500) } }), ctx);
  assert.equal(out.json.valid, false);
  assert.match((out.json.errors as string[])[0], /notes/);
});

// ---- script ---------------------------------------------------------------------------------

const para = (role: string, words: number, source_ids: number[] = [1]) => ({ role, text: 'word '.repeat(words).trim() + '.', source_ids });
const goodScript = () => ({
  sources: [{ id: 1, title: 'A', url: 'https://a' }, { id: 2, title: 'B', url: 'https://b' }],
  paragraphs: [para('intro', 40, []), ...[1, 2, 3, 4, 5].map(() => para('body', 50, [2])), para('outro', 30, [])],
});

test('a well-formed script passes', () => {
  assert.deepEqual(checkScript(goodScript()), []);
});

test('script rules each produce a readable error', () => {
  const s1 = goodScript(); s1.paragraphs[0].role = 'body';
  assert.match(checkScript(s1).join(), /first paragraph must be the intro/);
  const s2 = goodScript(); s2.paragraphs[2].source_ids = [9];
  assert.match(checkScript(s2).join(), /paragraph 2 cites unknown source 9/);
  const s3 = goodScript(); s3.paragraphs[3].source_ids = [];
  assert.match(checkScript(s3).join(), /paragraph 3 cites no source/);
  const s4 = goodScript(); s4.paragraphs = s4.paragraphs.slice(0, 4);
  assert.match(checkScript(s4).join(), /6 to 10 paragraphs/);
  const s5 = goodScript(); s5.paragraphs[1].text = '   ';
  assert.match(checkScript(s5).join(), /paragraph 1 is empty/);
  assert.match(checkScript({ paragraphs: 'nope' }).join(), /paragraphs/);
});

test('script word count limits', () => {
  const s = goodScript(); s.paragraphs.forEach((p) => { p.text = 'one two.'; });
  assert.match(checkScript(s).join(), /250 to 1400 words/);
});

// ---- voice timeline -------------------------------------------------------------------------

test('timeline places paragraphs and gives each a slot up to the next one', () => {
  const v = timeline([{ idx: 0, role: 'intro', text: 'a' }, { idx: 1, role: 'body', text: 'b' }, { idx: 2, role: 'outro', text: 'c' }],
    { path: '/data/shared/v.wav', duration_s: 10.8, parts: [{ start_s: 0, duration_s: 3 }, { start_s: 3.4, duration_s: 4 }, { start_s: 7.8, duration_s: 3 }] });
  assert.equal(v.total_s, 10.8);
  assert.deepEqual(v.paragraphs.map((p) => [p.start_s, p.slot_s]), [[0, 3.4], [3.4, 4.4], [7.8, 3]]);
});

// ---- storyboard -----------------------------------------------------------------------------

const slots = [{ idx: 0, text: 'a', start_s: 0, slot_s: 6 }, { idx: 1, text: 'b', start_s: 6, slot_s: 9 }];
const shot = (paragraph: number, duration_s: number, kind = 'still') => ({ paragraph, kind, duration_s, prompt: 'p', query: 'q' });

test('storyboard shots get start times and exact paragraph coverage', () => {
  const r = checkStoryboard({ shots: [shot(0, 3), shot(0, 3), shot(1, 4.5), shot(1, 4.5)] }, slots, 0.3);
  assert.deepEqual(r.errors, []);
  assert.deepEqual(r.shots.map((s) => [s.idx, s.start_s, s.duration_s]), [[0, 0, 3], [1, 3, 3], [2, 6, 4.5], [3, 10.5, 4.5]]);
});

test('storyboard within 15% is scaled to the voice, beyond is an error', () => {
  const near = checkStoryboard({ shots: [shot(0, 3.3), shot(0, 3.3), shot(1, 9)] }, slots, 0.5);
  assert.deepEqual(near.errors, []);
  assert.ok(Math.abs(near.shots[0].duration_s + near.shots[1].duration_s - 6) < 0.001);
  const far = checkStoryboard({ shots: [shot(0, 4), shot(0, 4), shot(1, 9)] }, slots, 0.5);
  assert.match(far.errors.join(), /paragraph 0: shots last 8.0s, voice 6.0s/);
});

test('storyboard reports missing paragraphs, bad lengths and unknown paragraphs', () => {
  const r = checkStoryboard({ shots: [shot(0, 6), shot(7, 3)] }, slots, 0.3);
  assert.match(r.errors.join(), /paragraph 1 has no shots/);
  assert.match(r.errors.join(), /unknown paragraph 7/);
  const short = checkStoryboard({ shots: [shot(0, 5), shot(0, 1), shot(1, 9)] }, slots, 0.3);
  assert.match(short.errors.join(), /shot 1 lasts 1.0s/);
});

test('storyboard turns AI shots over the cap into stills, latest first', () => {
  const r = checkStoryboard({ shots: [shot(0, 3, 'ai'), shot(0, 3, 'ai'), shot(1, 4.5, 'ai'), shot(1, 4.5)] }, slots, 0.3);
  assert.deepEqual(r.errors, []);
  assert.deepEqual(r.shots.map((s) => s.kind), ['ai', 'still', 'still', 'still']);
});

// ---- shot state machine ---------------------------------------------------------------------

const baseShot = { id: 7, idx: 2, status: 'pending', attempts: 0, fallback: false, image_path: null as string | null, qc: null };

test('a started shot moves to generating with its job', () => {
  const r = afterStart(baseShot, { ok: true, job_id: 'j1', image_path: '/s/i.png', qc: { status: 'PASS' }, source: { license: 'CC0' } });
  assert.equal(r.action, 'none');
  assert.deepEqual(r.update, { status: 'generating', job_id: 'j1', image_path: '/s/i.png', source: { license: 'CC0' }, qc: { image: { status: 'PASS' } }, last_error: null });
});

test('a failed start is retried, then falls back to the last image, else fails', () => {
  assert.deepEqual(afterStart(baseShot, { ok: false, reason: 'too small', image_path: '/s/a.png' }).update,
    { status: 'pending', attempts: 1, job_id: null, image_path: '/s/a.png', last_error: 'too small' });
  const last = { ...baseShot, attempts: MAX_ATTEMPTS - 1 };
  const fb = afterStart(last, { ok: false, reason: 'too small', image_path: '/s/b.png' });
  assert.equal(fb.action, 'fallback');
  assert.deepEqual(fb.update, { status: 'generating', attempts: MAX_ATTEMPTS, fallback: true, job_id: null, image_path: '/s/b.png', last_error: 'too small' });
  const dead = afterStart({ ...baseShot, attempts: 0 }, { ok: false, reason: 'set FAL_KEY', permanent: true });
  assert.deepEqual(dead.update, { status: 'failed', attempts: 1, job_id: null, last_error: 'set FAL_KEY' });
});

test('a running job means wait; a finished job means QC', () => {
  const s = { ...baseShot, status: 'generating', job_id: 'j1' };
  assert.equal(afterJob(s, { status: 'running' }).action, 'wait');
  assert.deepEqual(afterJob(s, { status: 'done', result: { path: '/s/c.mp4' } }), { action: 'qc', update: {} });
});

test('a failed job is retried like a failed start', () => {
  const s = { ...baseShot, status: 'generating', job_id: 'j1', image_path: '/s/i.png' };
  assert.equal(afterJob(s, { status: 'failed', error: 'render died' }).update.status, 'pending');
  assert.equal(afterJob(s, { status: 'failed', error: 'bad key', permanent: true }).action, 'fallback');
});

test('QC decides done or retry', () => {
  const s = { ...baseShot, status: 'generating', job_id: 'j1', qc: { image: { status: 'PASS' } } };
  const job = { status: 'done', result: { path: '/s/c.mp4' } };
  assert.deepEqual(afterQc(s, job, { status: 'QUESTIONABLE', reasons: ['frozen for 1.2s'] }).update,
    { status: 'done', asset_path: '/s/c.mp4', job_id: null, qc: { image: { status: 'PASS' }, clip: { status: 'QUESTIONABLE', reasons: ['frozen for 1.2s'] } } });
  assert.equal(afterQc(s, job, { status: 'FAIL', reasons: ['black frames'] }).update.status, 'pending');
});

test('a finished fallback render ends the shot as fallback; a failed one as failed', () => {
  const s = { ...baseShot, status: 'generating', fallback: true, attempts: 3, job_id: 'j9', image_path: '/s/i.png' };
  assert.deepEqual(afterJob(s, { status: 'done', result: { path: '/s/fb.mp4' } }),
    { action: 'none', update: { status: 'fallback', asset_path: '/s/fb.mp4', job_id: null } });
  assert.equal(afterJob(s, { status: 'failed', error: 'x' }).update.status, 'failed');
});

// ---- titles and description -----------------------------------------------------------------

test('titles must quote the script; description lists sources and photo credits', () => {
  const [out] = pickTitles(one({
    topic: 'Lighthouses',
    script_text: 'The first lamps burned whale oil.  Keepers lived on the rock.',
    output: { titles: [{ text: 'Whale oil and light', quote: 'burned  WHALE oil' }, { text: 'Made up', quote: 'invented fact' }], description: 'A short film.' },
    sources: [{ id: 1, title: 'Lighthouse history', url: 'https://example.org/l' }],
    credits: [{ license: 'CC BY', author: 'Ann', url: 'https://src/1' }, { license: 'generated', author: 'x', url: null }],
  }), ctx);
  assert.equal(out.json.title, 'Whale oil and light');
  assert.deepEqual(out.json.rejected, ['Made up']);
  const d = out.json.description as string;
  assert.match(d, /^A short film\./);
  assert.match(d, /Sources:\n- Lighthouse history https:\/\/example\.org\/l/);
  assert.match(d, /Photos:\n- Ann, CC BY, https:\/\/src\/1/);
  assert.doesNotMatch(d, /generated/);
});

test('when no title is backed by the script, the topic becomes the title', () => {
  const [out] = pickTitles(one({ topic: 'Lighthouses', script_text: 'abc', output: { titles: [{ text: 'X', quote: 'zzz' }], description: '' }, sources: [], credits: [] }), ctx);
  assert.equal(out.json.title, 'Lighthouses');
});

// ---- stage results --------------------------------------------------------------------------

const stage = (status: string, attempts: number, outcome: Record<string, unknown>) =>
  stageResult(one({ video: { status, attempts }, outcome }), ctx)[0].json;

test('a successful stage moves to the next one and resets attempts', () => {
  assert.deepEqual(stage('queued', 1, { ok: true }), { status: 'voice', attempts: 0, last_error: null, stage: 'script' });
  assert.equal(stage('storyboard', 0, { ok: true }).status, 'production');
  assert.equal(stage('packaging', 0, { ok: true }).status, 'ready');
});

test('an unfinished async stage stays where it is', () => {
  assert.deepEqual(stage('assembly', 1, { ok: true, done: false }), { status: 'assembly', attempts: 1, last_error: null, stage: 'assembly' });
});

test('errors are retried, the third one fails the video', () => {
  assert.deepEqual(stage('voice', 0, { ok: false, error: 'timeout' }), { status: 'voice', attempts: 1, last_error: 'timeout', stage: 'voice' });
  assert.equal(stage('voice', 2, { ok: false, error: 'timeout' }).status, 'failed');
  assert.equal(stage('voice', 0, { ok: false, error: 'bad key', permanent: true }).status, 'failed');
});

// ---- assembly -------------------------------------------------------------------------------

const row = (idx: number, paragraph: number, status: string, duration_s: number) => ({ idx, paragraph, status, duration_s, asset_path: `/s/${idx}.mp4` });

test('segments cut inside a paragraph and fade between paragraphs', () => {
  const r = planSegments([row(0, 0, 'done', 3), row(1, 0, 'fallback', 3), row(2, 1, 'done', 4)]);
  assert.deepEqual(r.segments.map((s) => [s.path, s.duration_s, s.transition]), [['/s/0.mp4', 3, 'cut'], ['/s/1.mp4', 3, 'fade'], ['/s/2.mp4', 4, 'cut']]);
});

test('a failed shot gives its time to the previous shot (or the next one if it is first)', () => {
  const r = planSegments([row(0, 0, 'failed', 2), row(1, 0, 'done', 3), row(2, 1, 'failed', 4), row(3, 1, 'done', 1)]);
  assert.deepEqual(r.segments.map((s) => [s.path, s.duration_s]), [['/s/1.mp4', 9], ['/s/3.mp4', 1]]);
  assert.deepEqual(r.merged, [0, 2]);
});

test('assembly with no usable shot is an error', () => {
  assert.throws(() => assemblyPlan(one({ shots: [row(0, 0, 'failed', 2)] }), ctx), /no usable shots/);
});

// ---- error formatting -----------------------------------------------------------------------

test('error text is escaped and short', () => {
  const [out] = formatError(one({ workflow: { name: 'video <runner>' }, execution: { lastNodeExecuted: 'Render', error: { message: 'x'.repeat(900) } } }), ctx);
  const text = out.json.text as string;
  assert.match(text, /video &lt;runner&gt;/);
  assert.ok(text.length <= 700 && text.includes('…'));
});
