/** Code node "Validate Script": the narration must have the agreed shape, and every body paragraph
 *  must cite a source the script lists. Errors go back to the model once for a repair. */
import type { Ctx, Item } from './lib/types.ts';

export interface Paragraph { role: string; text: string; source_ids: number[] }
export interface Script { sources: Array<{ id: number; title: string; url: string }>; paragraphs: Paragraph[] }

export function checkScript(output: unknown): string[] {
  const s = (output ?? {}) as Partial<Script>;
  if (!Array.isArray(s.paragraphs)) return ['paragraphs must be a list'];
  const errors: string[] = [];
  const ids = new Set((Array.isArray(s.sources) ? s.sources : []).map((src) => src?.id));
  const paras = s.paragraphs;
  if (paras.length < 6 || paras.length > 10) errors.push(`need 6 to 10 paragraphs, got ${paras.length}`);
  if (paras[0]?.role !== 'intro') errors.push('the first paragraph must be the intro');
  if (paras[paras.length - 1]?.role !== 'outro') errors.push('the last paragraph must be the outro');
  let words = 0;
  paras.forEach((p, i) => {
    const text = typeof p?.text === 'string' ? p.text.trim() : '';
    if (!text) errors.push(`paragraph ${i} is empty`);
    words += text ? text.split(/\s+/).length : 0;
    if (i > 0 && i < paras.length - 1) {
      if (p?.role !== 'body') errors.push(`paragraph ${i} must be a body paragraph`);
      const cited = Array.isArray(p?.source_ids) ? p.source_ids : [];
      if (!cited.length) errors.push(`paragraph ${i} cites no source`);
      for (const id of cited) if (!ids.has(id)) errors.push(`paragraph ${i} cites unknown source ${id}`);
    }
  });
  if (words < 250 || words > 1400) errors.push(`the script must have 250 to 1400 words, got ${words}`);
  return errors;
}

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const errors = checkScript(json.output);
    if (errors.length) return { json: { valid: false, errors, output: json.output } };
    const s = json.output as Script;
    const script = { sources: s.sources, paragraphs: s.paragraphs.map((p) => ({ ...p, text: p.text.trim() })) };
    return { json: { valid: true, errors: [], script } };
  });
}
