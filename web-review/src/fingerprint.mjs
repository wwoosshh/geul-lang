import fs from 'node:fs';
import { createHash } from 'node:crypto';

// Bind each analysis to the actual local implementation, rather than trusting
// a manually bumped version string after a checker bug fix.
const files = ['core.mjs', 'typescript.mjs', 'project.mjs', 'module-index.mjs', 'jsx.mjs', 'jsx-property.mjs', 'jsx-guards.mjs', 'jsx-path.mjs', 'jsx-reference.mjs', 'jsx-flow.mjs', 'jsx-prefix.mjs', 'bindings.mjs', 'component-props.mjs', 'prop-expression.mjs', 'output-prop-links.mjs', 'function-results.mjs', 'source-context.mjs', 'result-preview.mjs', 'const-bindings.mjs', 'record-slice.mjs', 'record-diff.mjs', 'array-diff.mjs', 'change-rules.mjs', 'condition-view.mjs', 'presentation.mjs', 'report.mjs', 'cli.mjs', 'fingerprint.mjs'];
const sha256 = createHash('sha256');
files.push('reading.mjs', 'ir-structure.mjs', 'call-entry.mjs', 'call-entry-links.mjs', 'string-intrinsics.mjs', 'discovery.mjs');
files.push('change-discovery.mjs', '../scripts/diff-spans.mjs');
files.push('discovery-replay.mjs');
for (const file of files) {
  sha256.update(file + '\0');
  sha256.update(fs.readFileSync(new URL(file, import.meta.url)));
  sha256.update('\0');
}
sha256.update(fs.readFileSync(new URL('../package-lock.json', import.meta.url)));
// Native string operations depend on the runtime's Unicode data. A result
// recorded on a different runtime must be re-lifted and checked there.
export const ENGINE_RUNTIME = Object.freeze({ node: process.version, v8: process.versions.v8,
  unicode: process.versions.unicode, icu: process.versions.icu, platform: process.platform, arch: process.arch });
sha256.update('\0runtime\0' + JSON.stringify(ENGINE_RUNTIME));
export const ENGINE_SHA256 = sha256.digest('hex');
