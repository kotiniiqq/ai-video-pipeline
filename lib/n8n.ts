/** Small builders for the node types the pipeline uses, so workflow files read as flows.
 *  Versions match n8n 2.40. Worker URLs and credentials are placeholders resolved per environment. */
import { node, trigger, workflow } from '@n8n/workflow-sdk';

import { cred, envValue } from '../kit/placeholders.ts';

export const WORKER = envValue('workerUrl');
export const SHARED = envValue('sharedDir');
const PG_CRED = cred('postgres', 'pipeline-db');

/** Postgres query; `params` is an n8n expression body that evaluates to an array ($1, $2, ...). */
export function pg(name: string, query: string, params?: string, extra: Record<string, unknown> = {}) {
  return node({
    type: 'n8n-nodes-base.postgres',
    version: 2.7,
    config: {
      name,
      ...extra,
      parameters: { operation: 'executeQuery', query, options: params ? { queryReplacement: `={{ ${params} }}` } : {} },
      credentials: PG_CRED,
    },
  });
}

/** A call to the worker. `path` may contain {{ }} expressions; `body` is an expression body for a JSON object.
 *  `tolerant` returns error responses as data (the body has `detail`) instead of failing the run. */
export function worker(name: string, method: 'GET' | 'POST', path: string, body?: string,
                       opts: { timeout?: number; tolerant?: boolean; extra?: Record<string, unknown> } = {}) {
  const options: Record<string, unknown> = { timeout: opts.timeout ?? 120_000 };
  if (opts.tolerant) options.response = { response: { neverError: true } };
  return node({
    type: 'n8n-nodes-base.httpRequest',
    version: 4.5,
    config: {
      name,
      ...(opts.extra ?? {}),
      parameters: {
        method,
        url: `=${WORKER}${path}`,
        ...(body ? { sendBody: true, specifyBody: 'json', jsonBody: `={{ JSON.stringify(${body}) }}` } : {}),
        options,
      },
    },
  });
}

/** Glue that only reshapes data, one item at a time (keeps n8n's item pairing). Logic lives in code/. */
export function glue(name: string, jsCode: string) {
  return node({
    type: 'n8n-nodes-base.code',
    version: 2,
    config: { name, parameters: { mode: 'runOnceForEachItem', jsCode } },
  });
}

export function startedBy(name: string) {
  return trigger({
    type: 'n8n-nodes-base.executeWorkflowTrigger',
    version: 1.2,
    config: { name, parameters: { inputSource: 'workflowInputs', workflowInputs: { values: [{ name: 'video_id', type: 'number' }] } } },
  });
}

export function every(name: string, seconds: number) {
  return trigger({
    type: 'n8n-nodes-base.scheduleTrigger',
    version: 1.2,
    config: { name, parameters: { rule: { interval: [{ field: 'seconds', secondsInterval: seconds }] } } },
  });
}

export function fail(name: string, message: string) {
  return node({ type: 'n8n-nodes-base.stopAndError', version: 1, config: { name, parameters: { errorMessage: `=${message}` } } });
}

/** The value a stage sub-workflow hands back to the runner. */
export function result(name: string, value: string) {
  return glue(name, `return { json: ${value} };`);
}

const cond = (expression: string) => ({
  options: { caseSensitive: true, leftValue: '', typeValidation: 'loose', version: 2 },
  conditions: [{ leftValue: `={{ ${expression} }}`, rightValue: '', operator: { type: 'boolean', operation: 'true', singleValue: true } }],
  combinator: 'and',
});

export function check(name: string, expression: string) {
  return node({ type: 'n8n-nodes-base.if', version: 2.2, config: { name, parameters: { conditions: cond(expression) } } });
}

/** Switch on a string; output i is cases[i], anything else goes nowhere. */
export function route(name: string, value: string, cases: string[]) {
  return node({
    type: 'n8n-nodes-base.switch',
    version: 3.2,
    config: {
      name,
      parameters: {
        rules: { values: cases.map((c) => ({ outputKey: c, renameOutput: true, conditions: cond(`${value} === ${JSON.stringify(c)}`) })) },
        options: {},
      },
    },
  });
}

export function webhook(name: string, method: 'GET' | 'POST', path: string) {
  return trigger({
    type: 'n8n-nodes-base.webhook',
    version: 2,
    config: { name, parameters: { httpMethod: method, path, responseMode: 'responseNode', options: {} } },
  });
}

export function respond(name: string, code: number, body: string) {
  return node({
    type: 'n8n-nodes-base.respondToWebhook',
    version: 1.1,
    config: { name, parameters: { respondWith: 'json', responseBody: `={{ JSON.stringify(${body}) }}`, options: { responseCode: code } } },
  });
}

/** Glue over all items at once (fan-in / fan-out). */
export function glueAll(name: string, jsCode: string) {
  return node({ type: 'n8n-nodes-base.code', version: 2, config: { name, parameters: { mode: 'runOnceForAllItems', jsCode } } });
}

type AnyNode = { name: string };
/** A workflow from a trigger and a list of edges [from, to, fromOutput?]. */
export function flow(name: string, start: AnyNode, edges: Array<[AnyNode, AnyNode, number?]>) {
  let wf: any = workflow(name, name).add(start as any);
  const seen = new Set([start.name]);
  for (const [a, b] of edges) {
    for (const n of [a, b]) if (!seen.has(n.name)) { wf = wf.add(n); seen.add(n.name); }
  }
  for (const [a, b, out = 0] of edges) wf = wf.connect(a, out, b, 0);
  return wf;
}
