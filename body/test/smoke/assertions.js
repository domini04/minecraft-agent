// Smoke test assertions
// Mirrors the envelope contract in body/src/utils/response.js.

class AssertionError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AssertionError';
  }
}

/**
 * Asserts that the envelope has the expected shape and success status.
 *
 * @param {object} envelope - The response envelope from /execute.
 * @param {object} opts
 * @param {string} [opts.tool] - Expected tool name.
 * @param {boolean} [opts.success=true] - Expected success value.
 */
function assertEnvelope(envelope, { tool, success = true } = {}) {
  if (!envelope || typeof envelope !== 'object') {
    throw new AssertionError(`assertEnvelope: expected an object, got ${typeof envelope}`);
  }

  if (typeof envelope.success !== 'boolean') {
    throw new AssertionError(`assertEnvelope: expected envelope.success to be boolean, got ${typeof envelope.success}`);
  }

  if (envelope.success !== success) {
    const errMsg = envelope.error ? ` (error: ${envelope.error.code}: ${envelope.error.message})` : '';
    throw new AssertionError(
      `assertEnvelope: expected success=${success}, got success=${envelope.success}${errMsg}`
    );
  }

  if (tool !== undefined && envelope.tool !== tool) {
    throw new AssertionError(
      `assertEnvelope: expected tool="${tool}", got tool="${envelope.tool}"`
    );
  }

  if (!Number.isFinite(envelope.duration_ms) || envelope.duration_ms < 0) {
    throw new AssertionError(
      `assertEnvelope: expected duration_ms to be a finite non-negative number, got ${envelope.duration_ms}`
    );
  }

  if (success) {
    if (!Object.prototype.hasOwnProperty.call(envelope, 'data')) {
      throw new AssertionError('assertEnvelope: success envelope missing "data" field');
    }
  } else {
    if (!envelope.error || typeof envelope.error.code !== 'string' || typeof envelope.error.message !== 'string') {
      throw new AssertionError(
        'assertEnvelope: failure envelope missing "error.code" or "error.message"'
      );
    }
  }
}

/**
 * Asserts that actual position is within tolerance (Euclidean) of target.
 *
 * @param {{ x: number, y: number, z: number }} actual
 * @param {{ x: number, y: number, z: number }} target
 * @param {number} [tolerance=1.5]
 */
function assertPositionNear(actual, target, tolerance = 1.5) {
  if (!actual || !target) {
    throw new AssertionError('assertPositionNear: actual and target must be objects');
  }

  const dx = (actual.x || 0) - (target.x || 0);
  const dy = (actual.y || 0) - (target.y || 0);
  const dz = (actual.z || 0) - (target.z || 0);
  const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);

  if (!Number.isFinite(dist) || dist > tolerance) {
    throw new AssertionError(
      `assertPositionNear: position (${actual.x},${actual.y},${actual.z}) is ${dist.toFixed(2)} blocks from target (${target.x},${target.y},${target.z}); tolerance=${tolerance}`
    );
  }
}

/**
 * Asserts that the change in item count between two inventory snapshots equals expectedDelta.
 *
 * @param {Array<{name: string, count: number}>} beforeInv
 * @param {Array<{name: string, count: number}>} afterInv
 * @param {string} itemName
 * @param {number} expectedDelta
 */
function assertInventoryDelta(beforeInv, afterInv, itemName, expectedDelta) {
  const countIn = (inv) =>
    (inv || [])
      .filter((item) => item.name === itemName)
      .reduce((sum, item) => sum + item.count, 0);

  const before = countIn(beforeInv);
  const after = countIn(afterInv);
  const delta = after - before;

  if (delta !== expectedDelta) {
    throw new AssertionError(
      `assertInventoryDelta: expected ${itemName} delta=${expectedDelta}, got delta=${delta} (before=${before}, after=${after})`
    );
  }
}

module.exports = {
  assertEnvelope,
  assertPositionNear,
  assertInventoryDelta,
  AssertionError,
};
