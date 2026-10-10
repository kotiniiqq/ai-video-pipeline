/** POST /webhook/video {topic, notes?} -> 202 {id} and the video is queued; invalid input -> 400.
 *
 *  New Video -> Validate Request -> Valid? -> Worker Mode -> Queue Video -> 202
 *                                         \-> 400 with the errors
 */
import { codeNode } from '../kit/code.ts';
import { check, flow, pg, respond, webhook, worker } from '../lib/n8n.ts';

const hook = webhook('New Video', 'POST', 'video');
const validate = codeNode('Validate Request', 'code/validate-intake.ts');
const valid = check('Valid?', '$json.valid');
const mode = worker('Worker Mode', 'GET', '/health', undefined, { timeout: 10_000 });
const queue = pg('Queue Video',
  "INSERT INTO videos (topic, notes, mode) VALUES ($1, NULLIF($2, ''), $3) RETURNING id::int AS id, status",
  "[ $('Validate Request').item.json.topic, $('Validate Request').item.json.notes ?? '', $json.mode ]");
const accepted = respond('Respond Queued', 202, "{ id: $json.id, status: $json.status, status_url: '/webhook/video-status?id=' + $json.id }");
const rejected = respond('Respond Invalid', 400, '{ errors: $json.errors }');

export default flow('intake', hook, [
  [hook, validate], [validate, valid], [valid, mode, 0], [mode, queue], [queue, accepted], [valid, rejected, 1],
]);
