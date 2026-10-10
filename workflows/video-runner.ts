/** Every 10 s: claim one video whose next stage can run, run that stage's workflow, record the result.
 *
 *  A video's status names the stage it waits for. The claim sets a lock, so overlapping runs and
 *  several n8n workers never take the same video; a crashed run frees it when the lock expires.
 *  Errors are retried up to three times (code/stage-result.ts), then the video is failed and reported.
 */
import { node } from '@n8n/workflow-sdk';

import { codeNode } from '../kit/code.ts';
import { workflowRef } from '../kit/placeholders.ts';
import { check, every, flow, glue, pg, worker } from '../lib/n8n.ts';

const STAGES: Record<string, string> = { queued: 'script', voice: 'voice', storyboard: 'storyboard', assembly: 'assembly', packaging: 'packaging' };
const stageIds = `({ ${Object.entries(STAGES).map(([status, wf]) => `${status}: '${workflowRef(wf)}'`).join(', ')} })[$json.status]`;

const tick = every('Every 10 Seconds', 10);
const claim = pg('Claim Video', `UPDATE videos v SET locked_until = now() + interval '15 minutes', updated_at = now()
FROM (SELECT id FROM videos WHERE status IN (${Object.keys(STAGES).map((s) => `'${s}'`).join(', ')})
      AND (locked_until IS NULL OR locked_until < now()) ORDER BY updated_at LIMIT 1 FOR UPDATE SKIP LOCKED) p
WHERE v.id = p.id RETURNING v.id::int AS video_id, v.status, v.attempts`);

const run = node({
  type: 'n8n-nodes-base.executeWorkflow',
  version: 1.3,
  config: {
    name: 'Run Stage',
    onError: 'continueErrorOutput',
    parameters: {
      source: 'database',
      workflowId: { __rl: true, mode: 'id', value: `={{ ${stageIds} }}` },
      workflowInputs: {
        mappingMode: 'defineBelow',
        value: { video_id: '={{ $json.video_id }}' },
        matchingColumns: [],
        schema: [{ id: 'video_id', displayName: 'video_id', required: false, defaultMatch: false, display: true, canBeUsedToMatch: true, type: 'number' }],
        attemptToConvertTypes: true,
        convertFieldsToString: false,
      },
      options: { waitForSubWorkflow: true },
    },
  },
});

const succeeded = glue('Stage Succeeded',
  "return { json: { video: $('Claim Video').first().json, outcome: { ok: true, done: $json.done !== false } } };");
const failed = glue('Stage Failed',
  "const e = $json.error; return { json: { video: $('Claim Video').first().json, outcome: { ok: false, error: String(e?.message ?? e ?? 'stage failed') } } };");
const apply = codeNode('Apply Stage Result', 'code/stage-result.ts');
const save = pg('Save Stage', `WITH log AS (
  INSERT INTO stage_log (video_id, stage, ok, detail) SELECT $1, $5, NULLIF($4, '') IS NULL, NULLIF($4, '') WHERE $6::boolean)
UPDATE videos SET status = $2, attempts = $3, last_error = NULLIF($4, ''), locked_until = NULL, updated_at = now()
WHERE id = $1 RETURNING id::int AS video_id, status, last_error`,
  "[ $('Claim Video').first().json.video_id, $json.status, $json.attempts, $json.last_error ?? '', $json.stage, $json.status !== $('Claim Video').first().json.status || !!$json.last_error ]");
const isFailed = check('Video Failed?', "$json.status === 'failed'");
const notify = worker('Report Failure', 'POST', '/notify', "{ text: 'Video ' + $json.video_id + ' failed: ' + $json.last_error }");

export default flow('video-runner', tick, [
  [tick, claim], [claim, run], [run, succeeded, 0], [run, failed, 1], [succeeded, apply], [failed, apply],
  [apply, save], [save, isFailed], [isFailed, notify, 0],
]);
