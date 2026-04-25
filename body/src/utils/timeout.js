// Timeout wrapper for Mineflayer tool calls.
//
// Uses Promise.race — the simplest option given that Mineflayer has no AbortSignal
// support. When the timeout fires, the bot operation may continue running in the
// background ("ghost operation"). This is acceptable because:
//   1. There is no practical way to force-stop a Mineflayer operation mid-execution.
//   2. The Python Brain will detect the timeout and issue a new command, which will
//      naturally interrupt the ghost operation.

class TimeoutError extends Error {
  constructor(ms) {
    super(`Action timed out after ${ms}ms`);
    this.name = 'TimeoutError';
    this.code = 'TIMEOUT';
  }
}

function withTimeout(promise, ms) {
  let timeoutId;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new TimeoutError(ms)), ms);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timeoutId));
}

module.exports = { withTimeout, TimeoutError };
