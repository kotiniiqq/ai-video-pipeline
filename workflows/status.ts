/** GET /webhook/video-status?id=<id> -> where the video is: stage, shots finished, cost, files, last error. */
import { check, flow, pg, respond, webhook } from '../lib/n8n.ts';

const hook = webhook('Status Request', 'GET', 'video-status');
const load = pg('Load Status', `SELECT v.id::int AS id, v.topic, v.status, v.mode, v.attempts, v.last_error, v.title,
  v.final_path, v.srt_path, v.thumbnail_path, v.final_qc, v.description,
  (SELECT count(*)::int FROM shots s WHERE s.video_id = v.id) AS shots_total,
  (SELECT count(*)::int FROM shots s WHERE s.video_id = v.id AND s.status IN ('done', 'fallback', 'failed')) AS shots_finished,
  (SELECT count(*)::int FROM shots s WHERE s.video_id = v.id AND s.status = 'fallback') AS shots_fallback,
  (SELECT count(*)::int FROM shots s WHERE s.video_id = v.id AND s.attempts > 0) AS shots_retried,
  (SELECT coalesce(sum(usd), 0)::float FROM costs c WHERE c.video_id = v.id) AS cost_usd
FROM videos v WHERE v.id = $1`, '[ Number($json.query.id) || 0 ]', { alwaysOutputData: true });
const found = check('Found?', '!!$json.id');
const ok = respond('Respond Status', 200, '$json');
const missing = respond('Respond Unknown', 404, "{ error: 'unknown video' }");

export default flow('status', hook, [[hook, load], [load, found], [found, ok, 0], [found, missing, 1]]);
