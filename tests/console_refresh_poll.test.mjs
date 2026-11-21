import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const filename = new URL('../src/agenttalk/web_static/console.js', import.meta.url);
const marker = '  // ------------------------------------------------------------ boot\n';
let source = fs.readFileSync(filename, 'utf8').replace(/\r\n/g, '\n');
assert.ok(source.includes(marker));
source = source.replace(marker, `  globalThis.hooks = {
    startEndpointPoll,
    refreshNow,
    install: function (fetcher) {
      fetchState = fetcher;
      fetchAttention = function () { return Promise.resolve(); };
      state.view = 'overview';
    },
    installFeeds: function (feeds, view) {
      fetchAttention = feeds.attention; fetchLeadChat = feeds.chat; fetchIntents = feeds.intents;
      fetchGates = feeds.gates; fetchRiskRegister = feeds.risk; state.view = view;
    },
    startReal: function (view) {
      renderActiveView = function () {};
      renderChrome = function () {};
      startEndpointPoll(view === 'gates' ? fetchGates : fetchRiskRegister);
    },
    go,
    rootEntry: function () {
      state.view = 'risk-register';
      fetchSession = fetchIntents = fetchLeadChat = fetchLearning = fetchOnboarding = fetchGates = fetchOwnership = function () {};
      fetchRootPayloads();
    },
    switchRoot: function () {
      rootGeneration++;
      state.selectedRootId = 'project-b';
      this.rootEntry();
    },
  };\n\n` + marker);

let now = 0;
let nextTimer = 1;
const timers = new Map();
const ctx = {
  console,
  document: { readyState: 'loading', addEventListener() {} },
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  performance: { now() { return now; } },
  setTimeout(fn, delay) { const id = nextTimer++; timers.set(id, { fn, at: now + delay }); return id; },
  clearTimeout(id) { timers.delete(id); },
  setInterval() { throw new Error('data polling must not use setInterval'); },
  clearInterval() {},
};
ctx.globalThis = ctx;
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(source, ctx);
const hooks = ctx.hooks;
const requests = [];
let displayed = '';
let inFlight = false;
ctx.fetch = (url) => new Promise((resolve, reject) => requests.push({ url, resolve, reject }));
function fetcher() {
  if (inFlight) return;
  inFlight = true;
  return ctx.fetch()
    .then((value) => { displayed = value; }).finally(() => { inFlight = false; });
}
async function flush() { for (let i = 0; i < 16; i++) await Promise.resolve(); }
async function settle(index, value, fail = false) {
  if (fail) requests[index].reject(new Error('network failed'));
  else requests[index].resolve(value);
  await flush();
}
async function advance(ms) {
  const target = now + ms;
  while (true) {
    const due = [...timers].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) break;
    now = due[1].at;
    timers.delete(due[0]);
    due[1].fn();
    await flush();
  }
  now = target;
}

hooks.install(fetcher);
hooks.startEndpointPoll(fetcher);
const scenario = process.argv[2];
if (scenario === 'busy') {
  hooks.refreshNow();
  hooks.refreshNow();
  hooks.refreshNow();
  assert.equal(requests.length, 1);
  await settle(0, 'old');
  assert.equal(requests.length, 2, 'three clicks queue exactly one follow-up');
  await settle(1, 'new');
  assert.equal(displayed, 'new');
  assert.equal(requests.length, 2);
  assert.equal(timers.size, 1);
} else if (scenario === 'followup') {
  hooks.refreshNow();
  await settle(0, 'first');
  assert.equal(requests.length, 2);
  hooks.refreshNow();
  await settle(1, 'second');
  assert.equal(requests.length, 3, 'click during follow-up queues one more');
  await settle(2, 'third');
  assert.equal(displayed, 'third');
  assert.equal(timers.size, 1);
} else if (scenario === 'idle') {
  await settle(0, 'first');
  await advance(5000);
  hooks.refreshNow();
  assert.equal(requests.length, 2, 'idle click fetches now');
  await settle(1, 'second');
  await advance(9999);
  assert.equal(requests.length, 2, 'old timer cancelled and full wait preserved');
  await advance(1);
  assert.equal(requests.length, 3);
} else if (scenario === 'failure') {
  hooks.refreshNow();
  await settle(0, '', true);
  assert.equal(requests.length, 2, 'failure honors queued refresh');
  await settle(1, '', true);
  assert.equal(requests.length, 2, 'failure must not trigger automatic retry');
  assert.equal(timers.size, 1);
  await advance(9999);
  assert.equal(requests.length, 2);
  await advance(1);
  assert.equal(requests.length, 3);
} else if (scenario === 'throw') {
  let calls = 0;
  hooks.startEndpointPoll(() => { calls++; throw new Error('local failure'); });
  assert.equal(calls, 1);
  await advance(9999);
  assert.equal(calls, 1);
  await advance(1);
  assert.equal(calls, 2, 'synchronous errors keep the normal cadence');
} else if (scenario === 'switch-in-flight') {
  await settle(0, 'state');
  hooks.startReal('risk-register');
  hooks.switchRoot();
  assert.equal(requests.filter((r) => r.url && r.url.startsWith('/api/risk-register')).length, 2,
    'new project starts without waiting for the old project');
  assert.match(requests[2].url, /root=project-b/);
  hooks.refreshNow();
  await settle(1, { ok: false });
  assert.equal(requests.filter((r) => r.url && r.url.startsWith('/api/risk-register')).length, 2,
    'old completion must not start a follow-up');
  await settle(2, { ok: false });
  assert.equal(requests.filter((r) => r.url && r.url.startsWith('/api/risk-register')).length, 3,
    'new project follows up the click');
} else if (scenario.startsWith('outside-')) {
  const view = scenario.slice('outside-'.length);
  const path = view === 'gates' ? '/api/gates' : '/api/risk-register';
  await settle(0, 'state');
  hooks.startReal(view);
  await settle(1, { ok: false });
  if (view === 'gates') hooks.go(view); else hooks.rootEntry();
  assert.equal(requests.filter((r) => r.url === path).length, 2, 'the caller starts a request');
  hooks.refreshNow();
  hooks.refreshNow();
  await flush();
  assert.equal(requests.filter((r) => r.url === path).length, 2, 'no overlapping request');
  await settle(2, { ok: false });
  assert.equal(requests.filter((r) => r.url === path).length, 3, 'clicks start one follow-up');
} else if (scenario.startsWith('view-')) {
  const view = scenario.slice(5);
  const pending = {};
  const feeds = {};
  for (const name of ['attention', 'chat', 'intents', 'gates', 'risk']) {
    pending[name] = [];
    feeds[name] = () => new Promise((resolve) => pending[name].push(resolve));
    hooks.startEndpointPoll(feeds[name]);
  }
  hooks.installFeeds(feeds, view);
  hooks.refreshNow();
  for (const name of Object.keys(feeds)) assert.equal(pending[name].length, 1, name + ' must not overlap');
  await settle(0, 'state');
  for (const name of Object.keys(feeds)) pending[name][0]();
  await flush();
  const active = { 'lead-chat': ['chat', 'intents'], sessions: ['intents'], gates: ['gates'],
    'risk-register': ['risk'] }[view];
  assert.equal(requests.length, 2, 'state must follow up');
  for (const name of Object.keys(feeds)) {
    assert.equal(pending[name].length, name === 'attention' || active.includes(name) ? 2 : 1, name);
  }
} else {
  throw new Error('unknown scenario');
}
