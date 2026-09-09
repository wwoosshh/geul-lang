import fs from 'node:fs';
import assert from 'node:assert/strict';
import { encode, decode } from '../src/core.mjs';
import { hash } from '../src/typescript.mjs';

const bytes = fs.readFileSync(new URL('../corpus/mobile-flow-inputs.json', import.meta.url));
export const inputSpecificationSha256 = hash(bytes);
export const inputSpecification = JSON.parse(bytes);
export const mobileProfiles = inputSpecification.profiles.map(profile => {
  assert.deepEqual(Object.keys(profile.fields).sort(), ['openMenu', 'openSidebar', 'scrolledOutside', 'viewModeEnabled']);
  let rows = [{}];
  for (const [name, values] of Object.entries(profile.fields)) {
    assert.ok(Array.isArray(values) && values.length > 0 && values.length <= 8);
    rows = rows.flatMap(row => values.map(value => ({ ...row, [name]: decode(value) })));
    assert.ok(rows.length <= 1024);
  }
  const domains = { defaultUIEnabled: [false, true], scrollBackToContentUIEnabled: [false, true], appState: rows.map(row => encode(row)) };
  const inputs = [];
  for (const defaultUIEnabled of domains.defaultUIEnabled) for (const scrollBackToContentUIEnabled of domains.scrollBackToContentUIEnabled) for (const appState of domains.appState) inputs.push({ defaultUIEnabled, scrollBackToContentUIEnabled, appState });
  return { id: profile.id, domains, inputs };
});
