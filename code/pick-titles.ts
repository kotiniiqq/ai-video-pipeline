/** Code node "Pick Title": keep only titles whose quote really occurs in the script, and build the
 *  description with the sources and photo credits (generated images need no credit). */
import type { Ctx, Item } from './lib/types.ts';

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, ' ').trim();

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const output = (json.output ?? {}) as { titles?: Array<{ text: string; quote: string }>; description?: string };
    const script = norm(String(json.script_text ?? ''));
    const options = (output.titles ?? []).map((t) => ({ text: String(t.text ?? '').trim(), quote: String(t.quote ?? ''),
                                                        verified: !!t.quote && script.includes(norm(String(t.quote))) }));
    const verified = options.filter((o) => o.verified && o.text);
    const sources = (json.sources ?? []) as Array<{ title: string; url: string }>;
    const credits = ((json.credits ?? []) as Array<{ license: string; author: string; url: string | null }>)
      .filter((c) => c && c.license !== 'generated');
    const parts = [String(output.description ?? '').trim()];
    if (sources.length) parts.push(`Sources:\n${sources.map((s) => `- ${s.title} ${s.url}`).join('\n')}`);
    if (credits.length) parts.push(`Photos:\n${credits.map((c) => `- ${c.author}, ${c.license}${c.url ? `, ${c.url}` : ''}`).join('\n')}`);
    return { json: {
      title: verified[0]?.text ?? String(json.topic ?? ''),
      title_options: options,
      rejected: options.filter((o) => !o.verified).map((o) => o.text),
      description: parts.filter(Boolean).join('\n\n'),
    } };
  });
}
