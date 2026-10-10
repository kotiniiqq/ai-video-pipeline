/** Code node "Apply Stage Result": where a video goes after a stage ran.
 *  A video's status names the stage it waits for; 'production' is driven by the shot runner. */
import type { Ctx, Item } from './lib/types.ts';

export const MAX_ATTEMPTS = 3;
const NEXT: Record<string, string> = { queued: 'voice', voice: 'storyboard', storyboard: 'production', assembly: 'packaging', packaging: 'ready' };
export const STAGE: Record<string, string> = { queued: 'script', voice: 'voice', storyboard: 'storyboard', assembly: 'assembly', packaging: 'packaging' };

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const video = json.video as { status: string; attempts: number };
    const outcome = (json.outcome ?? {}) as { ok?: boolean; done?: boolean; error?: string; permanent?: boolean };
    const stage = STAGE[video.status] ?? video.status;
    if (outcome.ok) {
      if (outcome.done === false) return { json: { status: video.status, attempts: video.attempts, last_error: null, stage } };
      return { json: { status: NEXT[video.status] ?? 'failed', attempts: 0, last_error: null, stage } };
    }
    const attempts = video.attempts + 1;
    const error = String(outcome.error ?? 'stage failed').slice(0, 1000);
    const status = outcome.permanent || attempts >= MAX_ATTEMPTS ? 'failed' : video.status;
    return { json: { status, attempts, last_error: error, stage } };
  });
}
