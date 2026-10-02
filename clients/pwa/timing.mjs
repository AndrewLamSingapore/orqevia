// Optional, local-only PWA timing recorder. Never receives objective text,
// task IDs, credentials, headers, result text, or server response bodies.
const STAGES = new Set([
  'submit_start', 'submit_ack', 'events_start', 'events_end',
  'status_start', 'status_end', 'first_contribution', 'render_end',
  'terminal',
]);

export class TaskTiming {
  constructor({enabled = false, clock = () => performance.now()} = {}) {
    this.enabled = enabled === true;
    this.clock = clock;
    this.origin = null;
    this.samples = [];
  }

  start() {
    this.origin = null;
    this.samples = [];
    if (!this.enabled) return false;
    const now = this.clock();
    if (!Number.isFinite(now) || now < 0) throw new RangeError('invalid monotonic clock');
    this.origin = now;
    this.samples.push({stage: 'submit_start', elapsed_ms: 0});
    return true;
  }

  mark(stage) {
    if (!this.enabled || this.origin === null) return false;
    if (!STAGES.has(stage) || stage === 'submit_start') throw new TypeError('invalid timing stage');
    const now = this.clock();
    const previous = this.samples.at(-1)?.elapsed_ms ?? 0;
    const elapsed = now - this.origin;
    if (!Number.isFinite(elapsed) || elapsed < previous) throw new RangeError('nonmonotonic clock');
    if (this.samples.length >= 128) return false;
    if ((stage === 'first_contribution' || stage === 'terminal') && this.samples.some(item => item.stage === stage)) return false;
    this.samples.push({stage, elapsed_ms: Math.round(elapsed * 1000) / 1000});
    return true;
  }

  snapshot() {
    return {schema: 'jarvis.pwa.timing.v1', enabled: this.enabled, samples: this.samples.map(item => ({...item}))};
  }
}
