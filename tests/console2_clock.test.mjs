// The console page must not depend on the real date. These checks pin what the harness promises:
// the page's clock is the fixtures' NOW plus the harness clock, and the 30-day "Later" keep is
// measured on that clock. Run: node tests/console2_clock.test.mjs
// The suite also runs it with the real clock moved far forward and back (console2_clock_shift.mjs).
import assert from 'node:assert/strict';
import { createRunner, walk } from './console2_harness.mjs';
import { ATT_ITEM, NOW, agent, env, root } from './console2_fixtures.mjs';
import { LEAD, boot, server, stream } from './console2_app.mjs';

const { test, run } = createRunner('console2 clock');
const LATER = 'agenttalk.console2.later';
const DAY = 86400e3;

const calm = () => [root({ project_id: 'proj-a', agents: [agent(LEAD, { since: 3000 })], recent: [env(LEAD, 'x', 'message', 5)] })];
const one = { roots: calm, attention: () => ({ target_root_project_id: 'proj-a', items: [ATT_ITEM({ id: 'e1', title: 'A', age: 900 })] }) };
const cards = (dom) => walk(stream(dom)).filter((n) => (n.className || '').split(' ').includes('c2-card'));
const deferredAt = (ts) => ({ [LATER]: JSON.stringify({ deferred: { 'proj-a': { e1: ts } }, snoozed: {} }) });

test('the page clock is NOW plus the harness clock, not the real date', async () => {
  const { sandbox, clock } = await boot(server(one));
  assert.equal(sandbox.Date.now(), NOW + clock.perf);
  assert.equal(new sandbox.Date().getTime(), NOW + clock.perf);
  clock.perf += 5 * DAY;
  assert.equal(sandbox.Date.now(), NOW + 5 * DAY);
  assert.equal(new sandbox.Date(2020, 0, 1).getUTCFullYear(), 2020, 'a date with arguments is untouched');
});

test('a stored deferral younger than 30 days on the page clock is kept across a reload', async () => {
  const { dom } = await boot(server(one), { storage: deferredAt(NOW - 29 * DAY) });
  assert.equal(cards(dom).length, 0, 'the card is still deferred');
});

test('a stored deferral older than 30 days on the page clock is dropped', async () => {
  const { dom } = await boot(server(one), { storage: deferredAt(NOW - 31 * DAY) });
  assert.equal(cards(dom).length, 1, 'the expired deferral no longer hides the card');
});

run();
