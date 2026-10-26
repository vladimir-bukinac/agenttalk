// Preload for the console node tests (node --import): moves the REAL clock by
// AGENTTALK_TEST_CLOCK_OFFSET_MS milliseconds, so a test can prove it does not depend on today's date.
// It shifts the host's Date and the Date of every vm context a harness creates WITHOUT a Date of its
// own (that is what a page sees when nothing pins its clock). A harness that gives its page its own
// Date is unaffected, which is the point.
import vm from 'node:vm';

const offset = Number(process.env.AGENTTALK_TEST_CLOCK_OFFSET_MS || 0);
if (offset) {
  const RealDate = Date;
  const shifted = (Base) => class ShiftedDate extends Base {
    constructor(...args) { if (args.length === 0) super(Base.now() + offset); else super(...args); }
    static now() { return Base.now() + offset; }
  };
  globalThis.Date = shifted(RealDate);
  const createContext = vm.createContext;
  vm.createContext = function patched(sandbox, ...rest) {
    const ctx = createContext.call(this, sandbox, ...rest);
    if (!Object.prototype.hasOwnProperty.call(sandbox || {}, 'Date')) {
      vm.runInContext(
        `Date = (function (Base, off) { return class ShiftedDate extends Base {
          constructor(...a) { if (a.length === 0) super(Base.now() + off); else super(...a); }
          static now() { return Base.now() + off; } }; })(Date, ${offset});`,
        ctx,
      );
    }
    return ctx;
  };
}
