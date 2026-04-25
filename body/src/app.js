// Express app configuration
// Separated from server.js for testability (supertest imports this directly)

const express = require('express');
const { getBotStatus, getBot } = require('./bot');
const tools = require('./tools/index');
const { buildSuccess, buildError } = require('./utils/response');
const { withTimeout, TimeoutError } = require('./utils/timeout');

const ACTION_TIMEOUT_MS = parseInt(process.env.ACTION_TIMEOUT_MS, 10) || 4 * 60 * 1000;

// Wrap async route handlers so rejected promises forward to error middleware (Express 4).
const asyncHandler = (fn) => (req, res, next) =>
  Promise.resolve(fn(req, res, next)).catch(next);

const app = express();

// JSON parsing middleware
app.use(express.json());

// Content-Type logging middleware (lenient parsing with warnings)
app.use((req, res, next) => {
  if (req.method === 'POST' || req.method === 'PUT' || req.method === 'PATCH') {
    const contentType = req.headers['content-type'];
    if (contentType && !contentType.includes('application/json')) {
      console.warn(`[WARN] Unexpected Content-Type: ${contentType}`);
    }
  }
  next();
});

// Health check + bot status endpoint
app.get('/status', (req, res) => {
  res.json({ ok: true, bot: getBotStatus() });
});

// RPC tool execution endpoint
app.post('/execute', asyncHandler(async (req, res) => {
  const start = process.hrtime.bigint();
  const durationMs = () => Number(process.hrtime.bigint() - start) / 1_000_000;

  const { tool: toolName, params = {} } = req.body || {};

  // Validate: tool field is required
  if (!toolName || typeof toolName !== 'string') {
    return res.status(400).json(
      buildError(null, 'INVALID_PARAMS', '"tool" must be a non-empty string', null, durationMs())
    );
  }

  // Validate: tool must be registered
  const handler = tools[toolName];
  if (!handler) {
    return res.status(400).json(
      buildError(toolName, 'UNKNOWN_TOOL', `Unknown tool: "${toolName}"`, {
        available: Object.keys(tools),
      }, durationMs())
    );
  }

  // Execute with timeout
  try {
    const data = await withTimeout(handler(params, getBot()), ACTION_TIMEOUT_MS);
    return res.json(buildSuccess(toolName, data, durationMs()));
  } catch (err) {
    const code = err instanceof TimeoutError ? 'TIMEOUT' : 'ACTION_FAILED';
    return res.json(buildError(toolName, code, err.message, null, durationMs()));
  }
}));

// 404 handler for unknown routes
app.use((req, res) => {
  res.status(404).json({
    success: false,
    error: {
      code: 'NOT_FOUND',
      message: `Route ${req.method} ${req.path} not found`,
    },
  });
});

// Global error handler — catches unexpected throws from asyncHandler
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  console.error('[Body] Unhandled error:', err);
  res.status(500).json({
    success: false,
    error: { code: 'INTERNAL_ERROR', message: 'An unexpected error occurred' },
    tool: null,
    duration_ms: null,
  });
});

module.exports = app;
