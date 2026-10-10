/** Code node "Format Error": a short, HTML-safe message about a failed workflow run. */
import type { Ctx, Item } from './lib/types.ts';

const MAX = 600;

export function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export default function main(items: Item[], _ctx: Ctx): Item[] {
  return items.map(({ json }) => {
    const execution = (json.execution ?? {}) as { lastNodeExecuted?: string; url?: string; error?: { message?: string } };
    const workflow = (json.workflow ?? {}) as { name?: string };
    let message = String(execution.error?.message ?? 'unknown error');
    if (message.length > MAX) message = `${message.slice(0, MAX)}…`;
    const lines = [`Workflow ${workflow.name ?? 'unknown'} failed at node ${execution.lastNodeExecuted ?? 'unknown'}`, message];
    if (execution.url) lines.push(execution.url);
    return { json: { text: escapeHtml(lines.join('\n')) } };
  });
}
