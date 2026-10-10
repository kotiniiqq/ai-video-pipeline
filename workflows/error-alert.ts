/** Error workflow: every other workflow points its settings.errorWorkflow here.
 *  Error Trigger -> Format Error (tested module) -> worker /notify (Telegram if configured, else a log line). */
import { trigger } from '@n8n/workflow-sdk';

import { codeNode } from '../kit/code.ts';
import { flow, worker } from '../lib/n8n.ts';

const onError = trigger({ type: 'n8n-nodes-base.errorTrigger', version: 1, config: { name: 'On Workflow Error' } });
const format = codeNode('Format Error', 'code/format-error.ts');
const send = worker('Send Alert', 'POST', '/notify', '{ text: $json.text }', { timeout: 15_000 });

export default flow('error-alert', onError, [[onError, format], [format, send]]);
