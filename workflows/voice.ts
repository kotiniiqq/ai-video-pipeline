/** Stage "voice": every paragraph is spoken separately, joined with short pauses, placed on a
 *  timeline (code/voice-timeline.ts), and turned into subtitles. */
import { codeNode } from '../kit/code.ts';
import { flow, glueAll, pg, result, SHARED, startedBy, worker } from '../lib/n8n.ts';

const start = startedBy('Start Voice');
const load = pg('Load Script', 'SELECT id::int AS video_id, script FROM videos WHERE id = $1', '[ $json.video_id ]');
const split = glueAll('Split Paragraphs', `const v = $input.first().json;
const dir = '${SHARED}/videos/' + v.video_id + '/voice/';
return v.script.paragraphs.map((p, idx) => ({ json: { idx, role: p.role, text: p.text, out: dir + 'p' + String(idx).padStart(2, '0') + '.wav' } }));`);
const speak = worker('Speak Paragraph', 'POST', '/tts', '{ text: $json.text, out: $json.out }', { timeout: 300_000 });
const join = worker('Join Narration', 'POST', '/audio/concat',
  `{ paths: $('Speak Paragraph').all().map(i => i.json.path), out: '${SHARED}/videos/' + $('Load Script').first().json.video_id + '/voice/voice.wav', gap_s: 0.35 }`,
  { extra: { executeOnce: true } });
const timelineInput = glueAll('Timeline Input',
  "return [{ json: { paragraphs: $('Split Paragraphs').all().map(i => ({ idx: i.json.idx, role: i.json.role, text: i.json.text })), concat: $input.first().json } }];");
const timeline = codeNode('Build Timeline', 'code/voice-timeline.ts');
const subtitles = worker('Write Subtitles', 'POST', '/subtitles',
  `{ paragraphs: $json.voice.paragraphs.map(p => ({ text: p.text, start_s: p.start_s, duration_s: p.duration_s })), out: '${SHARED}/videos/' + $('Load Script').first().json.video_id + '/subtitles.srt' }`);
const save = pg('Save Voice', `WITH c AS (INSERT INTO costs (video_id, provider, model, usd) VALUES ($1, 'tts', 'voice', $4::numeric))
UPDATE videos SET voice = $2::jsonb, srt_path = $3, updated_at = now() WHERE id = $1 RETURNING id::int AS video_id`,
  "[ $('Load Script').first().json.video_id, JSON.stringify($('Build Timeline').first().json.voice), $json.path, $('Speak Paragraph').all().reduce((a, i) => a + (i.json.cost_usd || 0), 0) ]");
const done = result('Voice Done', '{ ok: true }');

export default flow('voice', start, [
  [start, load], [load, split], [split, speak], [speak, join], [join, timelineInput], [timelineInput, timeline],
  [timeline, subtitles], [subtitles, save], [save, done],
]);
