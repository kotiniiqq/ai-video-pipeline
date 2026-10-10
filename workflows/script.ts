/** Stage "script": the model writes the narration; code checks it; one repair round with the errors.
 *
 *  Load Video -> Write Script -> Validate Script -> OK? -> Save Script -> done
 *                                                 \-> Repair Script -> Validate Repaired Script -> OK? -> Save Script
 *                                                                                                 \-> error (runner retries)
 */
import { codeNode } from '../kit/code.ts';
import { check, fail, flow, pg, result, startedBy, worker } from '../lib/n8n.ts';

const start = startedBy('Start Script');
const load = pg('Load Video', "SELECT id::int AS video_id, topic, coalesce(notes, '') AS notes FROM videos WHERE id = $1", '[ $json.video_id ]');
const input = "{ topic: $('Load Video').first().json.topic, notes: $('Load Video').first().json.notes }";
const write = worker('Write Script', 'POST', '/llm', `{ task: 'script', input: ${input} }`, { timeout: 600_000 });
const validate = codeNode('Validate Script', 'code/validate-script.ts');
const ok = check('Script OK?', '$json.valid');
const repair = worker('Repair Script', 'POST', '/llm',
  `{ task: 'script', input: ${input}, repair: { previous: $json.output, errors: $json.errors } }`, { timeout: 600_000 });
const revalidate = codeNode('Validate Repaired Script', 'code/validate-script.ts');
const repairedOk = check('Repaired OK?', '$json.valid');
const rejected = fail('Script Rejected', "{{ 'the script failed validation twice: ' + $json.errors.join('; ') }}");
const cost = "($('Write Script').first().json.cost_usd || 0) + ($('Repair Script').isExecuted ? $('Repair Script').first().json.cost_usd || 0 : 0)";
const save = pg('Save Script', `WITH c AS (INSERT INTO costs (video_id, provider, model, usd) VALUES ($1, 'llm', $3, $4::numeric))
UPDATE videos SET script = $2::jsonb, updated_at = now() WHERE id = $1 RETURNING id::int AS video_id`,
  `[ $('Load Video').first().json.video_id, JSON.stringify($json.script), $('Write Script').first().json.model, ${cost} ]`);
const done = result('Script Done', '{ ok: true }');

export default flow('script', start, [
  [start, load], [load, write], [write, validate], [validate, ok], [ok, save, 0], [ok, repair, 1],
  [repair, revalidate], [revalidate, repairedOk], [repairedOk, save, 0], [repairedOk, rejected, 1], [save, done],
]);
