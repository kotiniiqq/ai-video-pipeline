/** Code node "Validate Request": clean the topic and notes of a new video request.
 *  Values stay plain strings; the SQL that stores them uses query parameters. */
import type { Ctx, Item } from './lib/types.ts';

export function cleanText(value: unknown): string {
  if (typeof value !== 'string') return '';
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, '').replace(/\s+/g, ' ').trim();
}

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const body = (json.body ?? {}) as Record<string, unknown>;
    const topic = cleanText(body.topic);
    const notes = cleanText(body.notes);
    const errors: string[] = [];
    if (topic.length < 3 || topic.length > 200) errors.push('topic must be 3 to 200 characters');
    if (notes.length > 1000) errors.push('notes must be at most 1000 characters');
    return { json: errors.length ? { valid: false, errors } : { valid: true, errors: [], topic, notes: notes || null } };
  });
}
