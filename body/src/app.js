// Express app configuration
// Separated from server.js for testability (supertest imports this directly)

const express = require('express');

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

// Health check endpoint
app.get('/status', (req, res) => {
  res.json({ ok: true });
});

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

module.exports = app;
