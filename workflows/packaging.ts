/** Stage "packaging": titles that quote the script (code/pick-titles.ts), a description with sources
 *  and photo credits, a thumbnail, and a notification that the video is ready. */
import { codeNode } from '../kit/code.ts';
import { flow, glue, pg, result, SHARED, startedBy, worker } from '../lib/n8n.ts';

const start = startedBy('Start Packaging');
const load = pg('Load Video', `SELECT v.id::int AS video_id, v.topic, v.script, v.final_path,
  (SELECT coalesce(json_agg(s.source ORDER BY s.idx), '[]'::json) FROM shots s
     WHERE s.video_id = v.id AND s.source IS NOT NULL AND s.status IN ('done', 'fallback')) AS credits,
  (SELECT s.image_path FROM shots s WHERE s.video_id = v.id AND s.image_path IS NOT NULL AND s.status IN ('done', 'fallback')
     ORDER BY (s.kind = 'still') DESC, s.idx LIMIT 1) AS cover
FROM videos v WHERE v.id = $1`, '[ $json.video_id ]');
const scriptText = "$('Load Video').first().json.script.paragraphs.map(p => p.text).join('\\n\\n')";
const write = worker('Write Titles', 'POST', '/llm',
  `{ task: 'packaging', input: { topic: $('Load Video').first().json.topic, script_text: ${scriptText} } }`, { timeout: 600_000 });
const input = glue('Titles Input', `const v = $('Load Video').first().json;
return { json: { topic: v.topic, script_text: ${scriptText}, output: $json.output, sources: v.script.sources, credits: v.credits } };`);
const pick = codeNode('Pick Title', 'code/pick-titles.ts');
const thumb = worker('Draw Thumbnail', 'POST', '/thumbnail',
  `{ image_path: $('Load Video').first().json.cover, text: $json.title, out: '${SHARED}/videos/' + $('Load Video').first().json.video_id + '/thumbnail.jpg' }`);
const save = pg('Save Package', `WITH c AS (INSERT INTO costs (video_id, provider, model, usd) VALUES ($1, 'llm', $6, $7::numeric))
UPDATE videos SET title = $2, title_options = $3::jsonb, description = $4, thumbnail_path = $5, updated_at = now()
WHERE id = $1 RETURNING id::int AS video_id, title, final_path`,
  "[ $('Load Video').first().json.video_id, $('Pick Title').first().json.title, JSON.stringify($('Pick Title').first().json.title_options), $('Pick Title').first().json.description, $json.path, $('Write Titles').first().json.model, $('Write Titles').first().json.cost_usd || 0 ]");
const notify = worker('Report Ready', 'POST', '/notify', "{ text: 'Video ' + $json.video_id + ' is ready: ' + $json.title + '\\n' + $json.final_path }");
const done = result('Packaging Done', '{ ok: true }');

export default flow('packaging', start, [
  [start, load], [load, write], [write, input], [input, pick], [pick, thumb], [thumb, save], [save, notify], [notify, done],
]);
