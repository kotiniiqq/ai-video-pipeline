/** Code node "Build Timeline": where each paragraph sits in the joined narration.
 *  A paragraph's slot runs until the next paragraph starts, so pauses belong to a shot too. */
import type { Ctx, Item } from './lib/types.ts';

export interface Concat { path: string; duration_s: number; parts: Array<{ start_s: number; duration_s: number }> }
export interface TimedParagraph { idx: number; role: string; text: string; start_s: number; duration_s: number; slot_s: number }

const r3 = (n: number) => Math.round(n * 1000) / 1000;

export function timeline(paragraphs: Array<{ idx: number; role: string; text: string }>, concat: Concat) {
  if (paragraphs.length !== concat.parts.length) {
    throw new Error(`timeline: ${paragraphs.length} paragraphs but ${concat.parts.length} audio parts`);
  }
  const timed: TimedParagraph[] = paragraphs.map((p, i) => {
    const part = concat.parts[i];
    const next = i + 1 < concat.parts.length ? concat.parts[i + 1].start_s : concat.duration_s;
    return { ...p, start_s: r3(part.start_s), duration_s: r3(part.duration_s), slot_s: r3(next - part.start_s) };
  });
  return { path: concat.path, total_s: r3(concat.duration_s), paragraphs: timed };
}

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => ({
    json: { voice: timeline(json.paragraphs as Array<{ idx: number; role: string; text: string }>, json.concat as Concat) },
  }));
}
