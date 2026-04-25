// Response shape builders for the /execute endpoint.
// Pure functions — no req/res dependency, easy to unit test.

function buildSuccess(tool, data, durationMs) {
  return { success: true, data, tool, duration_ms: durationMs };
}

function buildError(tool, code, message, context, durationMs) {
  return {
    success: false,
    error: { code, message, ...(context ? { context } : {}) },
    tool,
    duration_ms: durationMs,
  };
}

module.exports = { buildSuccess, buildError };
