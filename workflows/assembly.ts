/** Stage "assembly": start the master render once, then poll it on later runs until it is done and
 *  passes final QC (length matches the narration, -14 LUFS, no black). Rendering takes minutes, so the
 *  stage answers "not done yet" instead of blocking the runner. */
import { codeNode } from '../kit/code.ts';
import { check, fail, flow, glueAll, pg, result, route, SHARED, startedBy, worker } from '../lib/n8n.ts';

const start = startedBy('Start Assembly');
const load = pg('Load Video', 'SELECT id::int AS video_id, coalesce(render_job, \'\') AS render_job, voice FROM videos WHERE id = $1',
  '[ $json.video_id ]');
const rendering = check('Render Started?', '!!$json.render_job');
const dir = `'${SHARED}/videos/' + $('Load Video').first().json.video_id`;

const shots = pg('Load Shots', 'SELECT idx, paragraph, status, duration_s::float AS duration_s, asset_path FROM shots WHERE video_id = $1 ORDER BY idx',
  "[ $('Load Video').first().json.video_id ]");
const collect = glueAll('Collect Shots', 'return [{ json: { shots: $input.all().map(i => i.json) } }];');
const plan = codeNode('Plan Segments', 'code/assembly-plan.ts');
const bed = worker('Make Music Bed', 'POST', '/render/music-bed',
  `{ duration_s: $('Load Video').first().json.voice.total_s, out: ${dir} + '/music.m4a' }`);
const render = worker('Start Render', 'POST', '/render/master',
  `{ segments: $('Plan Segments').first().json.segments.map(s => ({ path: s.path, duration_s: s.duration_s, transition: s.transition })), voice_path: $('Load Video').first().json.voice.path, music_path: $json.path, out: ${dir} + '/final.mp4' }`);
const saveJob = pg('Save Render Job', 'UPDATE videos SET render_job = $2, music_path = $3, updated_at = now() WHERE id = $1 RETURNING id::int AS video_id',
  "[ $('Load Video').first().json.video_id, $json.job_id, $('Make Music Bed').first().json.path ]");
const started = result('Render Started', '{ ok: true, done: false }');

const poll = worker('Poll Render', 'GET', '/jobs/{{ $json.render_job }}', undefined, { timeout: 30_000, tolerant: true });
const state = route('Render State', "($json.status ?? 'failed')", ['done', 'failed', 'queued', 'running']);
const waiting = result('Still Rendering', '{ ok: true, done: false }');
const finalQc = worker('Check Final', 'POST', '/qc/final',
  "{ path: $json.result.path, expected_duration: $('Load Video').first().json.voice.total_s }", { timeout: 300_000 });
const passed = check('Final OK?', "$json.status === 'PASS'");
const saveFinal = pg('Save Final', `UPDATE videos SET final_path = $2, final_qc = $3::jsonb, render_job = NULL, updated_at = now()
WHERE id = $1 RETURNING id::int AS video_id`, "[ $('Load Video').first().json.video_id, $('Poll Render').first().json.result.path, JSON.stringify($json) ]");
const done = result('Assembly Done', '{ ok: true }');
const saveRejected = pg('Save Rejected Final', 'UPDATE videos SET final_qc = $2::jsonb, render_job = NULL, updated_at = now() WHERE id = $1 RETURNING $3::text AS reasons',
  "[ $('Load Video').first().json.video_id, JSON.stringify($json), $json.reasons.join('; ') ]");
const qcFailed = fail('Final QC Failed', "{{ 'final QC failed: ' + $json.reasons }}");
const clearJob = pg('Clear Render Job', 'UPDATE videos SET render_job = NULL, updated_at = now() WHERE id = $1 RETURNING id::int AS video_id',
  "[ $('Load Video').first().json.video_id ]");
const renderFailed = fail('Render Failed', "{{ 'render failed: ' + $('Poll Render').first().json.error }}");

export default flow('assembly', start, [
  [start, load], [load, rendering],
  [rendering, shots, 1], [shots, collect], [collect, plan], [plan, bed], [bed, render], [render, saveJob], [saveJob, started],
  [rendering, poll, 0], [poll, state],
  [state, finalQc, 0], [finalQc, passed], [passed, saveFinal, 0], [saveFinal, done], [passed, saveRejected, 1], [saveRejected, qcFailed],
  [state, clearJob, 1], [clearJob, renderFailed], [state, waiting, 2], [state, waiting, 3],
]);
