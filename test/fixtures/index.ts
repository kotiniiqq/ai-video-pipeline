/** The kit's own example workflows, used to test the kit independently of this repo's pipeline. */
import path from 'node:path';

import { listWorkflowSources, loadEnvironments } from '../../kit/build.ts';
import { ROOT } from '../../kit/code.ts';

const DIR = path.join(ROOT, 'test', 'fixtures');
export const FIXTURE = {
  sources: listWorkflowSources(path.join(DIR, 'workflows')),
  environments: loadEnvironments(path.join(DIR, 'environments.json')),
};
