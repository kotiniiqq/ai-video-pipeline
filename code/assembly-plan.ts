/** Code node "Plan Segments": shot clips in order, with transitions, for the master render.
 *  Cuts inside a paragraph, a fade where the narration moves to the next paragraph.
 *  A failed shot gives its time to the previous usable shot (or the next one, if it comes first). */
import type { Ctx, Item } from './lib/types.ts';

export interface ShotRow { idx: number; paragraph: number; status: string; duration_s: number | string; asset_path: string | null }
export interface Segment { path: string; duration_s: number; transition: 'fade' | 'cut'; paragraph: number }

const r3 = (n: number) => Math.round(n * 1000) / 1000;

export function planSegments(rows: ShotRow[]) {
  const ordered = [...rows].sort((a, b) => a.idx - b.idx);
  const segments: Segment[] = [];
  const merged: number[] = [];
  let carry = 0; // time of failed shots before the first usable one
  for (const s of ordered) {
    const d = Number(s.duration_s);
    if ((s.status === 'done' || s.status === 'fallback') && s.asset_path) {
      segments.push({ path: s.asset_path, duration_s: r3(d + carry), transition: 'cut', paragraph: s.paragraph });
      carry = 0;
    } else {
      merged.push(s.idx);
      if (segments.length) segments[segments.length - 1].duration_s = r3(segments[segments.length - 1].duration_s + d);
      else carry += d;
    }
  }
  if (!segments.length) throw new Error('assembly: no usable shots');
  segments.forEach((seg, i) => { if (i + 1 < segments.length && segments[i + 1].paragraph !== seg.paragraph) seg.transition = 'fade'; });
  return { segments, merged };
}

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => ({ json: planSegments(json.shots as ShotRow[]) }));
}
