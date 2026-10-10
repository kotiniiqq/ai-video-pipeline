/** Every 10 s: move up to six shots one step forward, and send finished videos to assembly.
 *
 *  pending    -> Start Shot (picture + image QC + render job)          -> Step After Start ┐
 *  generating -> Poll Shot Job                                         -> Step After Job   ├-> Next Action
 *  Next Action: qc -> Check Clip -> Step After QC -> After QC; fallback -> Start Fallback; none -> Save Shot
 *
 *  Every decision (retry, fallback, done, failed) is made by code/shot-step.ts; this flow only
 *  calls the worker and stores what the step decided.
 */
import { codeNode } from '../kit/code.ts';
import { every, flow, glue, pg, route, SHARED, worker } from '../lib/n8n.ts';

const tick = every('Every 10 Seconds', 10);
const claim = pg('Claim Shots', `UPDATE shots s SET updated_at = now()
FROM (SELECT id FROM shots WHERE status IN ('pending', 'generating') AND updated_at < now() - interval '5 seconds'
        AND video_id IN (SELECT id FROM videos WHERE status = 'production')
      ORDER BY updated_at LIMIT 6 FOR UPDATE SKIP LOCKED) p
WHERE s.id = p.id
RETURNING s.id::int AS id, s.video_id::int AS video_id, s.idx, s.paragraph, s.kind, s.status, s.attempts, s.fallback,
  s.job_id, s.image_path, s.qc, s.prompt, s.query, s.duration_s::float AS duration_s`);
const finish = pg('Finish Production', `UPDATE videos v SET status = 'assembly', updated_at = now()
WHERE v.status = 'production' AND EXISTS (SELECT 1 FROM shots s WHERE s.video_id = v.id)
  AND NOT EXISTS (SELECT 1 FROM shots s WHERE s.video_id = v.id AND s.status IN ('pending', 'generating'))
RETURNING v.id::int AS video_id`);

const byStatus = route('Shot Status', '$json.status', ['pending', 'generating']);
const outDir = `'${SHARED}/videos/' + $json.video_id + '/shots'`;

const startShot = worker('Start Shot', 'POST', '/shots/start',
  `{ kind: $json.kind, idx: $json.idx, prompt: $json.prompt, query: $json.query, duration_s: $json.duration_s, out_dir: ${outDir}, attempt: $json.attempts }`,
  { timeout: 300_000, tolerant: true });
const startInput = glue('Start Step Input', "return { json: { phase: 'start', shot: $('Claim Shots').item.json, start: $json } };");
const afterStart = codeNode('Step After Start', 'code/shot-step.ts');

const poll = worker('Poll Shot Job', 'GET', '/jobs/{{ $json.job_id }}', undefined, { timeout: 30_000, tolerant: true });
const jobInput = glue('Job Step Input',
  "return { json: { phase: 'job', shot: $('Claim Shots').item.json, job: $json.status ? $json : { status: 'failed', error: String($json.detail ?? 'job not found') } } };");
const afterJob = codeNode('Step After Job', 'code/shot-step.ts');

const next = route('Next Action', '$json.action', ['qc', 'fallback', 'none']);
const checkClip = worker('Check Clip', 'POST', '/qc/clip',
  '{ path: $json.job.result.path, expected_duration: Number($json.shot.duration_s), expect_face: false }', { tolerant: true });
const qcInput = glue('QC Step Input',
  "const s = $('Next Action').item.json; return { json: { phase: 'qc', shot: s.shot, job: s.job, qc: $json.status ? $json : { status: 'FAIL', reasons: [String($json.detail ?? 'clip QC failed')] } } };");
const afterQc = codeNode('Step After QC', 'code/shot-step.ts');
const afterQcRoute = route('After QC', '$json.action', ['fallback', 'none']);

const fallback = worker('Start Fallback', 'POST', '/shots/fallback',
  `{ image_path: $json.update.image_path, idx: $json.shot.idx, duration_s: Number($json.shot.duration_s), out_dir: '${SHARED}/videos/' + $json.shot.video_id + '/shots', context: { shot_id: $json.shot_id, update: $json.update, cost_usd: $json.cost_usd } }`);
const fallbackUpdate = glue('Fallback Update',
  'return { json: { shot_id: $json.context.shot_id, update: { ...$json.context.update, job_id: $json.job_id }, cost_usd: $json.context.cost_usd || 0 } };');

const save = pg('Save Shot', `WITH c AS (INSERT INTO costs (video_id, shot_id, provider, model, usd)
  SELECT video_id, id, 'shot', kind, $3::numeric FROM shots WHERE id = $1 AND $3::numeric > 0)
UPDATE shots s SET
  status = COALESCE(x.u->>'status', s.status),
  attempts = COALESCE((x.u->>'attempts')::int, s.attempts),
  fallback = COALESCE((x.u->>'fallback')::boolean, s.fallback),
  job_id = CASE WHEN x.u ? 'job_id' THEN x.u->>'job_id' ELSE s.job_id END,
  image_path = CASE WHEN x.u ? 'image_path' THEN x.u->>'image_path' ELSE s.image_path END,
  asset_path = CASE WHEN x.u ? 'asset_path' THEN x.u->>'asset_path' ELSE s.asset_path END,
  qc = CASE WHEN x.u ? 'qc' THEN x.u->'qc' ELSE s.qc END,
  source = CASE WHEN x.u ? 'source' THEN x.u->'source' ELSE s.source END,
  last_error = CASE WHEN x.u ? 'last_error' THEN x.u->>'last_error' ELSE s.last_error END,
  updated_at = now()
FROM (SELECT $2::jsonb AS u) x WHERE s.id = $1 RETURNING s.id::int AS id, s.status`,
  '[ $json.shot_id, JSON.stringify($json.update), Number($json.cost_usd || 0) ]');

export default flow('shot-runner', tick, [
  [tick, claim], [tick, finish], [claim, byStatus],
  [byStatus, startShot, 0], [startShot, startInput], [startInput, afterStart], [afterStart, next],
  [byStatus, poll, 1], [poll, jobInput], [jobInput, afterJob], [afterJob, next],
  [next, checkClip, 0], [checkClip, qcInput], [qcInput, afterQc], [afterQc, afterQcRoute],
  [next, fallback, 1], [afterQcRoute, fallback, 0], [fallback, fallbackUpdate], [fallbackUpdate, save],
  [next, save, 2], [afterQcRoute, save, 1],
]);
