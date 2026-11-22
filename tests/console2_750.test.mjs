import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { makeProtocol, makeDeadline, PHASE_BUDGETS_MS, firstDrawDiagnostics } from './console2_browser_check.mjs';

assert.equal(PHASE_BUDGETS_MS.firstDraw, 45000);
assert.match(firstDrawDiagnostics(['Failed to load resource']), /Failed to load resource/);
assert.match(firstDrawDiagnostics([]), /the page reported no errors/);
const socket = new EventEmitter();
socket.send = () => {};
const child = new EventEmitter();
const scenario = process.argv[2];
const protocol = makeProtocol(socket, child, () => ({ name: 'board-render', deadline: makeDeadline(1) }));
if (scenario === 'unanswered') {
  const start = Date.now();
  await assert.rejects(protocol.send('Runtime.evaluate'), /board-render/);
  assert.ok(Date.now() - start < 4000);
} else if (scenario === 'exit-and-close') {
  const a = protocol.send('A');
  const b = protocol.send('B');
  const start = Date.now();
  child.emit('exit', 1, null);
  await Promise.all([assert.rejects(a, /exit/i), assert.rejects(b, /exit/i)]);
  assert.ok(Date.now() - start < 1000, 'pending calls should fail promptly after exit');
  await assert.rejects(protocol.send('C'), /exit/i);
  const socket2 = new EventEmitter();
  socket2.send = (request) => {
    const { id } = JSON.parse(request);
    queueMicrotask(() => socket2.emit('message', { data: JSON.stringify({ id, result: { value: 42 } }) }));
  };
  const protocol2 = makeProtocol(socket2, new EventEmitter(), () => ({ name: 'keys', deadline: makeDeadline(10000) }));
  assert.deepEqual(await protocol2.send('answered'), { value: 42 });
  socket2.send = () => {};
  const d = protocol2.send('D');
  const e = protocol2.send('E');
  socket2.emit('close');
  await Promise.all([assert.rejects(d, /closed/i), assert.rejects(e, /closed/i)]);
} else {
  throw new Error('unknown test scenario');
}
process.stdout.write(JSON.stringify({ passed: 1 }));
