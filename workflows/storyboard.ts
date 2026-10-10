/** Stage "storyboard": the model plans shots per paragraph; code fits them to the narration
 *  (code/validate-storyboard.ts); one repair round; then the shots are stored for the shot runner. */
import { codeNode } from '../kit/code.ts';
import { check, fail, flow, glue, pg, result, startedBy, worker } from '../lib/n8n.ts';

const AI_SHARE_MAX = 0.3;
const start = startedBy('Start Storyboard');
// a retried stage starts clean: shots of an earlier attempt are dropped first
const load = pg('Load Voice', 'WITH d AS (DELETE FROM shots WHERE video_id = $1) SELECT id::int AS video_id, voice FROM videos WHERE id = $1',
  '[ $json.video_id ]');
const plan = worker('Plan Shots', 'POST', '/llm',
  `{ task: 'storyboard', input: { paragraphs: $json.voice.paragraphs.map(p => ({ idx: p.idx, text: p.text, duration_s: p.slot_s })), ai_share_max: ${AI_SHARE_MAX} } }`,
  { timeout: 600_000 });
const toCheck = (name: string) => glue(name,
  `return { json: { output: $json.output, paragraphs: $('Load Voice').first().json.voice.paragraphs, ai_share_max: ${AI_SHARE_MAX} } };`);
const input = toCheck('Storyboard Input');
const validate = codeNode('Validate Storyboard', 'code/validate-storyboard.ts');
const ok = check('Storyboard OK?', '$json.valid');
const repair = worker('Repair Storyboard', 'POST', '/llm',
  `{ task: 'storyboard', input: { paragraphs: $('Load Voice').first().json.voice.paragraphs.map(p => ({ idx: p.idx, text: p.text, duration_s: p.slot_s })), ai_share_max: ${AI_SHARE_MAX} }, repair: { previous: $json.output, errors: $json.errors } }`,
  { timeout: 600_000 });
const repairedInput = toCheck('Repaired Storyboard Input');
const revalidate = codeNode('Validate Repaired Storyboard', 'code/validate-storyboard.ts');
const repairedOk = check('Repaired OK?', '$json.valid');
const rejected = fail('Storyboard Rejected', "{{ 'the storyboard failed validation twice: ' + $json.errors.join('; ') }}");
const cost = "($('Plan Shots').first().json.cost_usd || 0) + ($('Repair Storyboard').isExecuted ? $('Repair Storyboard').first().json.cost_usd || 0 : 0)";
const save = pg('Save Shots', `WITH c AS (INSERT INTO costs (video_id, provider, model, usd) VALUES ($1, 'llm', $3, $4::numeric)),
ins AS (INSERT INTO shots (video_id, idx, paragraph, kind, start_s, duration_s, prompt, query)
  SELECT $1, x.idx, x.paragraph, x.kind, x.start_s, x.duration_s, x.prompt, x.query
  FROM jsonb_to_recordset($2::jsonb) AS x(idx int, paragraph int, kind text, start_s numeric, duration_s numeric, prompt text, query text)
  RETURNING 1)
SELECT count(*)::int AS shots FROM ins`,
  `[ $('Load Voice').first().json.video_id, JSON.stringify($json.shots), $('Plan Shots').first().json.model, ${cost} ]`);
const done = result('Storyboard Done', '{ ok: true }');

export default flow('storyboard', start, [
  [start, load], [load, plan], [plan, input], [input, validate], [validate, ok], [ok, save, 0], [ok, repair, 1],
  [repair, repairedInput], [repairedInput, revalidate], [revalidate, repairedOk], [repairedOk, save, 0],
  [repairedOk, rejected, 1], [save, done],
]);
