/** Code node "Shot Step": the whole shot state machine as one pure function per event.
 *
 *  pending --start ok--> generating --job done--> (QC) --PASS/QUESTIONABLE--> done
 *     ^                      |                      |
 *     +---- retry (attempts < 3) <---- failed start / failed job / QC FAIL
 *  after the 3rd failure (or a permanent one): fallback = Ken Burns over the last image -> 'fallback';
 *  with no image to fall back on, the shot is 'failed' and assembly gives its time to a neighbour.
 */
import type { Ctx, Item } from './lib/types.ts';

export const MAX_ATTEMPTS = 3;

export interface Shot {
  id?: number; idx: number; status: string; attempts: number; fallback: boolean;
  image_path?: string | null; job_id?: string | null; qc?: Record<string, unknown> | null;
}
export interface StartResult { ok: boolean; job_id?: string; image_path?: string; qc?: unknown; source?: unknown; reason?: string; detail?: string; permanent?: boolean; cost_usd?: number }
export interface Job { status: string; result?: { path: string }; error?: string; permanent?: boolean }
export interface ClipQc { status: string; reasons?: string[] }
export interface Step { action: 'none' | 'wait' | 'qc' | 'fallback'; update: Record<string, unknown> }

function retry(shot: Shot, reason: string, permanent = false, imagePath = shot.image_path ?? null): Step {
  const attempts = shot.attempts + 1;
  if (!permanent && attempts < MAX_ATTEMPTS && !shot.fallback) {
    return { action: 'none', update: { status: 'pending', attempts, job_id: null, ...(imagePath ? { image_path: imagePath } : {}), last_error: reason } };
  }
  if (imagePath && !shot.fallback) {
    return { action: 'fallback', update: { status: 'generating', attempts, fallback: true, job_id: null, image_path: imagePath, last_error: reason } };
  }
  return { action: 'none', update: { status: 'failed', attempts, job_id: null, last_error: reason } };
}

export function afterStart(shot: Shot, res: StartResult): Step {
  if (res.ok) {
    return { action: 'none', update: { status: 'generating', job_id: res.job_id, image_path: res.image_path, source: res.source ?? null,
                                       qc: { image: res.qc }, last_error: null } };
  }
  return retry(shot, res.reason ?? res.detail ?? 'shot start failed', res.permanent ?? false, res.image_path ?? shot.image_path ?? null);
}

export function afterJob(shot: Shot, job: Job): Step {
  if (job.status === 'queued' || job.status === 'running') return { action: 'wait', update: {} };
  if (job.status === 'failed') return retry(shot, job.error ?? 'job failed', job.permanent ?? false);
  if (shot.fallback) return { action: 'none', update: { status: 'fallback', asset_path: job.result?.path, job_id: null } };
  return { action: 'qc', update: {} };
}

export function afterQc(shot: Shot, job: Job, qc: ClipQc): Step {
  if (qc.status === 'FAIL') return retry(shot, (qc.reasons ?? []).join('; ') || 'clip failed QC');
  return { action: 'none', update: { status: 'done', asset_path: job.result?.path, job_id: null, qc: { ...(shot.qc ?? {}), clip: qc } } };
}

/** items: { phase: 'start' | 'job' | 'qc', shot, start?, job?, qc? } -> { shot_id, action, update } */
export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const shot = json.shot as Shot;
    const step = json.phase === 'start' ? afterStart(shot, json.start as StartResult)
      : json.phase === 'job' ? afterJob(shot, json.job as Job)
      : afterQc(shot, json.job as Job, json.qc as ClipQc);
    const cost = Number((json.start as StartResult | undefined)?.cost_usd ?? 0);
    return { json: { shot_id: shot.id, shot, job: json.job ?? null, action: step.action, update: step.update, cost_usd: cost } };
  });
}
