/** Code node "Validate Storyboard": shots must cover every paragraph's slot in the narration.
 *  Small rounding by the model (within 15%) is scaled away; bigger gaps go back for a repair.
 *  AI shots beyond the cap become stills, latest first, instead of failing the whole plan. */
import type { Ctx, Item } from './lib/types.ts';

export interface Slot { idx: number; text: string; start_s: number; slot_s: number }
export interface PlannedShot { idx: number; paragraph: number; kind: 'ai' | 'still'; start_s: number; duration_s: number; prompt: string; query: string }

const MIN_S = 1.5;
const MAX_S = 12;
const TOLERANCE = 0.15;
const r3 = (n: number) => Math.round(n * 1000) / 1000;

export function checkStoryboard(output: unknown, slots: Slot[], aiShareMax: number): { errors: string[]; shots: PlannedShot[] } {
  const raw = (output as { shots?: unknown })?.shots;
  if (!Array.isArray(raw) || !raw.length) return { errors: ['shots must be a non-empty list'], shots: [] };
  const errors: string[] = [];
  const known = new Set(slots.map((s) => s.idx));
  for (const s of raw) if (!known.has(s?.paragraph)) errors.push(`a shot refers to unknown paragraph ${s?.paragraph}`);

  const shots: PlannedShot[] = [];
  for (const slot of slots) {
    const mine = raw.filter((s) => s?.paragraph === slot.idx);
    if (!mine.length) { errors.push(`paragraph ${slot.idx} has no shots`); continue; }
    const sum = mine.reduce((a, s) => a + Number(s.duration_s || 0), 0);
    if (Math.abs(sum / slot.slot_s - 1) > TOLERANCE) {
      errors.push(`paragraph ${slot.idx}: shots last ${sum.toFixed(1)}s, voice ${slot.slot_s.toFixed(1)}s`);
      continue;
    }
    let t = slot.start_s;
    mine.forEach((s, i) => {
      const last = i === mine.length - 1;
      const d = last ? r3(slot.start_s + slot.slot_s - t) : r3(Number(s.duration_s) * slot.slot_s / sum);
      shots.push({ idx: shots.length, paragraph: slot.idx, kind: s.kind === 'ai' ? 'ai' : 'still', start_s: r3(t), duration_s: d,
                   prompt: String(s.prompt ?? '').trim(), query: String(s.query ?? s.prompt ?? '').trim() });
      t += d;
    });
  }
  for (const s of shots) {
    if (s.duration_s < MIN_S || s.duration_s > MAX_S) errors.push(`shot ${s.idx} lasts ${s.duration_s.toFixed(1)}s (allowed ${MIN_S}-${MAX_S}s)`);
    if (!s.prompt) errors.push(`shot ${s.idx} has no prompt`);
  }
  const total = slots.reduce((a, s) => a + s.slot_s, 0);
  let ai = shots.filter((s) => s.kind === 'ai').reduce((a, s) => a + s.duration_s, 0);
  for (let i = shots.length - 1; i >= 0 && ai > aiShareMax * total + 1e-9; i--) {
    if (shots[i].kind === 'ai') { shots[i].kind = 'still'; ai -= shots[i].duration_s; }
  }
  return { errors, shots };
}

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const { errors, shots } = checkStoryboard(json.output, json.paragraphs as Slot[], Number(json.ai_share_max ?? 0.3));
    return { json: errors.length ? { valid: false, errors, output: json.output } : { valid: true, errors: [], shots } };
  });
}
