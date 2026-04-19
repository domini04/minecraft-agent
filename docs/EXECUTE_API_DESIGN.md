# `/execute` API — Design Document

**Phase**: 1 (Skeleton), Steps 1.5-1.6
**Status**: Draft — Awaiting Review
**Date**: 2026-03-08
**Depends On**: Decisions 15-21 in [DECISION_LOG.md](DECISION_LOG.md)

---

## 1. Role of the `/execute` Endpoint

The `/execute` endpoint is the **single entry point** through which the Brain (Python) commands the Body (Node.js) to perform actions in Minecraft. It is the most important piece of the HTTP bridge.

### What it does

```
Brain: "Mine 5 oak logs"
  │
  │  POST /execute
  │  {"tool": "mine", "params": {"target": "oak_log", "count": 5}}
  │
  ▼
Body: receives request → dispatches to mine handler → Mineflayer digs blocks → returns result
  │
  │  200 OK
  │  {"success": true, "data": {"items_collected": 5, ...}, "tool": "mine", "duration_ms": 3420}
  │
  ▼
Brain: parses result → decides next step
```

### Why it matters

Every tool call in the entire agent pipeline flows through this endpoint. In a typical "Get me a stone pickaxe" task, the Brain will call `/execute` roughly 8 times (mine logs, craft planks, craft sticks, craft table, place table, craft wooden pick, mine stone, craft stone pick). The endpoint must be:

1. **Reliable** — Never silently fail or hang
2. **Consistent** — Same response shape for all tools, success or failure
3. **Timed** — Always respond within a bounded time (4-minute action timeout)
4. **Informative** — Return enough context for the Brain (and Reflexion node) to understand what happened

### What it does NOT do

- **Authentication** — Localhost binding handles access control (Decision 21)
- **Queuing** — Synchronous, one-at-a-time (Decision 5). The Brain waits for each result.
- **State management** — The endpoint is stateless. Bot state lives in Mineflayer.

---

## 2. Request & Response Contract

Already decided in Decisions 15-18. Summarized here for implementation reference.

### Request

```json
POST /execute
Content-Type: application/json

{
  "tool": "mine",
  "params": {
    "target": "oak_log",
    "count": 5
  }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `tool` | string | Yes | One of the 6 registered tool names |
| `params` | object | No | Tool-specific parameters. Defaults to `{}` |

### Success Response (HTTP 200)

```json
{
  "success": true,
  "data": {
    "items_collected": 5,
    "item_type": "oak_log"
  },
  "tool": "mine",
  "duration_ms": 3420
}
```

### Error Response (HTTP 200)

Tool failures are application-level outcomes, not HTTP failures. Always 200.

```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "No oak_log found within search radius",
    "context": {
      "target": "oak_log",
      "search_radius": 64,
      "bot_position": {"x": 100, "y": 64, "z": 100}
    }
  },
  "tool": "mine",
  "duration_ms": 1250
}
```

### Protocol Errors (non-200)

Reserved for HTTP-layer problems only:

| Situation | HTTP Status | Body |
|-----------|-------------|------|
| Missing/empty `tool` field | 400 | `{success: false, error: {code: "INVALID_PARAMS", message: "..."}}` |
| Unknown tool name | 400 | `{success: false, error: {code: "UNKNOWN_TOOL", message: "...", context: {available: [...]}}}` |
| Malformed JSON | 400 | Express default (from `express.json()`) |
| Server crash | 500 | `{success: false, error: {code: "INTERNAL_ERROR", message: "..."}}` |

---

## 3. Implementation Patterns

### 3.1 Tool Dispatch — Object Registry (Dispatch Map)

**Chosen over**: switch statement, dynamic require, class-based strategy pattern

The dispatch map is a plain object mapping tool names to handler functions:

```javascript
const tools = {
  mine:           require('./mine'),
  craft:          require('./craft'),
  place_block:    require('./place_block'),
  navigate:       require('./navigate'),
  get_bot_status: require('./get_bot_status'),
  chat:           require('./chat'),
};

const handler = tools[toolName];
if (!handler) { /* unknown tool error */ }
```

**Why this pattern**:
- O(1) lookup (property access on an object)
- Unknown tool check is a single `if (!handler)` line
- Adding a tool = create file + one line in registry
- Self-documenting — all 6 tools visible at a glance
- No fall-through bugs (unlike switch)

**Why not the alternatives**:

| Pattern | Issue for our case |
|---------|--------------------|
| Switch statement | Verbose for 6+ cases. Adding tools means modifying the switch block. Fall-through risk. |
| Dynamic require (`require(\`./\${toolName}\`)`) | **Security risk** — path traversal. A crafted tool name could load arbitrary files. Requires a whitelist anyway, at which point you've rebuilt a dispatch map. |
| Class-based strategy | Over-engineered for 6 stateless async functions. Mineflayer bot state is external (the `bot` object), so class instances add ceremony with no benefit. |

### 3.2 Timeout — Promise.race

**Chosen over**: AbortController, manual setTimeout

Each tool call is wrapped with a timeout using `Promise.race`:

```javascript
function withTimeout(promise, ms) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new TimeoutError(ms)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId));
}
```

**Why this pattern**:
- Works with any Promise — no cooperation required from the handler
- `.finally()` ensures the timer is always cleared (no leaked `setTimeout`)
- Simple, explicit, immediately understandable

**The ghost operation caveat**: When the timeout fires, the Mineflayer operation **keeps running in the background**. The Express endpoint responds with a TIMEOUT error, but the bot may still be digging/walking. This is acceptable because:

1. Mineflayer has **no built-in cancellation** — there is no AbortSignal support on `bot.dig()`, `bot.pathfinder.goto()`, etc.
2. The Brain will detect the timeout and issue a new command, which will interrupt the ghost operation
3. The alternative (AbortController) would require polling `signal.aborted` between every Mineflayer call inside every handler — significant complexity for uncertain benefit

**Why not AbortController**: Cooperative cancellation only works when the callee checks the signal. Mineflayer methods don't accept an AbortSignal parameter. We'd have to wrap every internal Mineflayer call to periodically check `signal.aborted` — too much complexity for 6 tools.

### 3.3 Response Building — Helper Functions

**Chosen over**: response class, middleware-based formatting

Two plain functions that build the response objects:

```javascript
function buildSuccess(tool, data, durationMs) {
  return { success: true, data, tool, duration_ms: durationMs };
}

function buildError(tool, code, message, context, durationMs) {
  return {
    success: false,
    error: { code, message, context },
    tool,
    duration_ms: durationMs,
  };
}
```

**Why this pattern**:
- Zero framework magic — any reader can trace exactly what gets sent
- Pure functions — trivially unit-testable without mocking `req`/`res`
- Explicit — no hidden error swallowing

**Why not a response class**: Functionally identical to helper functions but requires more boilerplate. Classes add value when you have inheritance or state — we have neither.

**Why not middleware**: We have one route. Error-handling middleware is useful as a **safety net** for unexpected throws, but the primary response building should be explicit in the handler.

### 3.4 Duration Tracking — `process.hrtime.bigint()`

**Chosen over**: `Date.now()`, `performance.now()`

```javascript
const startTime = process.hrtime.bigint();
// ... do work ...
const durationMs = Number(process.hrtime.bigint() - startTime) / 1_000_000;
```

**Why**: Monotonic clock — immune to NTP clock adjustments that can affect `Date.now()`. Nanosecond precision (though we only report milliseconds). This is the idiom Node.js itself uses in its test suite.

`Date.now()` would also work fine at this scale — clock drift during a single request is negligible. But `process.hrtime.bigint()` is only 2 extra lines and is the modern practice.

### 3.5 Async Error Handling — asyncHandler wrapper (Express 4)

We're currently on **Express 4.22**, which does **not** automatically catch rejected promises from async route handlers. An unhandled rejection will either hang the request or crash the process.

**Solution**: A lightweight wrapper that catches async errors and forwards them to Express error middleware:

```javascript
const asyncHandler = (fn) => (req, res, next) =>
  Promise.resolve(fn(req, res, next)).catch(next);

app.post('/execute', asyncHandler(async (req, res) => {
  // async/await works safely here
}));
```

**Alternative**: Install `express-async-errors` (which does the same thing globally via monkey-patching). Either approach works; the explicit wrapper is more transparent.

**Future**: Express 5 handles this natively. We can drop the wrapper if/when we upgrade.

### 3.6 Request Validation — Manual checks

**Chosen over**: Zod, Joi, ajv, express-validator

For a single endpoint accepting `{tool, params}` with 6 known tool names, manual validation is appropriate:

```javascript
if (!tool || typeof tool !== 'string') {
  return res.status(400).json(buildError(null, 'INVALID_PARAMS', '"tool" is required'));
}
if (!tools[tool]) {
  return res.status(400).json(buildError(tool, 'UNKNOWN_TOOL', `Unknown tool: "${tool}"`, {
    available: Object.keys(tools),
  }));
}
```

**Why not a validation library**: We have one schema with 2 fields. Zod (8kb) or Joi (145kb) add a dependency for something that's 5 lines of if-checks. The dispatch map itself serves as the tool name whitelist. Per-tool param validation will come in Phase 2 when we implement the actual tools — we can reassess then.

---

## 4. File Organization

### Chosen: Handlers directory with thin registry

```
body/src/
  app.js                    # Express setup, routes, middleware (MODIFY)
  server.js                 # Entry point — listen + createBot (NO CHANGE)
  bot.js                    # Mineflayer bot module (NO CHANGE)
  tools/                    # NEW — tool handler directory
    index.js                # Dispatch map: { mine, craft, ... }
    mine.js                 # async (params, bot) => result
    craft.js
    place_block.js
    navigate.js
    get_bot_status.js
    chat.js
  utils/                    # NEW — shared utilities
    response.js             # buildSuccess, buildError helpers
    timeout.js              # withTimeout, TimeoutError
```

### Why this structure

- **Each tool handler is independently testable** — import the function, pass mock params and bot, assert the return value. No Express mocking needed.
- **Adding a tool** = create `tools/newTool.js` + one line in `tools/index.js`
- **Separation of concerns** — `app.js` handles HTTP plumbing (routing, middleware, validation). `tools/` handles Minecraft logic. `utils/` handles cross-cutting utilities.
- **Portfolio readability** — A reviewer opening the project sees clear organization, not a 500-line monolith.

### Why not alternatives

| Alternative | Issue |
|-------------|-------|
| Everything in `app.js` | Grows to 300-500 lines quickly. Can't test handlers without spinning up Express. |
| Single `execute.js` with inline handlers | Mixes HTTP routing with Minecraft logic. |
| `routes/` directory | We only have 2 routes. A dedicated routes directory is premature. Keep routes in `app.js` until there are more. |

---

## 5. Step 1.5 Scope (Scaffold)

Step 1.5 is the **scaffold only**. All 6 tool handlers will be stubs that throw `NotImplementedError`. The goal is to wire up the complete dispatch pipeline so that Phase 2 can implement tools one at a time by replacing stubs.

### What gets built

| Component | Content |
|-----------|---------|
| `tools/index.js` | Dispatch map with all 6 tool entries |
| `tools/mine.js` (and 5 others) | Stubs: `async (params, bot) => { throw new NotImplementedError('mine') }` |
| `utils/response.js` | `buildSuccess()` and `buildError()` helpers |
| `utils/timeout.js` | `withTimeout()` and `TimeoutError` class |
| `app.js` modifications | Add `POST /execute` route with dispatch, validation, timeout, timing |

### What gets deferred

| Concern | Deferred To |
|---------|-------------|
| Real tool implementations | Phase 2 (Core Tools) |
| Per-tool parameter validation | Phase 2 (each tool validates its own params) |
| Express 5 upgrade | Optional future improvement |
| Per-tool timeout overrides | Phase 2+ (if needed) |

### Verification criteria

```bash
# Missing tool field → 400 with INVALID_PARAMS
curl -s -X POST http://127.0.0.1:3000/execute \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

# Unknown tool → 400 with UNKNOWN_TOOL
curl -s -X POST http://127.0.0.1:3000/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "fly"}' | jq .

# Valid tool (stub) → 200 with NOT_IMPLEMENTED
curl -s -X POST http://127.0.0.1:3000/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "mine", "params": {"target": "oak_log", "count": 5}}' | jq .

# All responses include duration_ms
# All responses match the contract shape
```

---

## 6. Handler Signature Convention

Every tool handler follows the same function signature:

```javascript
/**
 * @param {Object} params - Tool-specific parameters from the request
 * @param {Object} bot - The Mineflayer bot instance
 * @returns {Object} - Data to include in the success response's `data` field
 * @throws {ToolError} - On expected failures (with error code and context)
 * @throws {Error} - On unexpected failures (caught by error middleware)
 */
async function mine(params, bot) {
  // Phase 2: Implement actual mining logic
  // For now:
  throw new NotImplementedError('mine');
}
```

### Why `(params, bot)` and not `(req, res)`

- **Testability** — Test a handler by passing a mock params object and mock bot. No Express mocking.
- **Separation** — Handlers don't know they're behind HTTP. They could be called from a CLI, a test, or a WebSocket adapter.
- **Single responsibility** — HTTP concerns (status codes, response shaping) stay in `app.js`. Minecraft concerns stay in handlers.

### Error conventions

Handlers communicate errors by throwing:

| Error Type | Meaning | Caught By |
|------------|---------|-----------|
| `ToolError(message, code, context)` | Expected failure (resource not found, path blocked, etc.) | Route handler → `buildError()` → 200 |
| `NotImplementedError(toolName)` | Stub tool (Step 1.5) | Route handler → `buildError()` → 200 |
| `TimeoutError(ms)` | `withTimeout` fired before handler resolved | Route handler → `buildError()` → 200 |
| Any other `Error` | Unexpected crash | Global error middleware → 500 |

---

## 7. Decision Summary

| # | Decision | Chosen | Alternatives Considered |
|---|----------|--------|------------------------|
| A | Dispatch pattern | Object registry (dispatch map) | switch, dynamic require, class strategy |
| B | Timeout mechanism | `Promise.race` + `.finally(clearTimeout)` | AbortController, manual setTimeout |
| C | Response building | Plain helper functions | Response class, middleware |
| D | Duration tracking | `process.hrtime.bigint()` | `Date.now()`, `performance.now()` |
| E | Async error handling | `asyncHandler` wrapper (Express 4) | `express-async-errors`, Express 5 upgrade |
| F | Request validation | Manual if-checks | Zod, Joi, ajv |
| G | File organization | `tools/` directory + `utils/` directory | Single file, inline handlers |
| H | Handler signature | `async (params, bot) => data` | `(req, res) => void` |

---

## References

- [Cancellation in JavaScript: Why It's Harder Than It Looks (Dec 2025)](https://blog.gaborkoos.com/posts/2025-12-23-Cancellation-In-JavaScript-Why-Its-Harder-Than-It-Looks/)
- [Managing Async Operations with AbortController — AppSignal (Feb 2025)](https://blog.appsignal.com/2025/02/12/managing-asynchronous-operations-in-nodejs-with-abortcontroller.html)
- [Switch Statements vs Object Maps — JSCrambler](https://jscrambler.com/blog/switch-statements-vs-object)
- [Express Official Error Handling Guide](https://expressjs.com/en/guide/error-handling.html)
- [Goodbye asyncHandler: Native Async Support in Express 5](https://dev.to/mahmud007/goodbye-asynchandler-native-async-support-in-express-5-2o9p)
- [Express Error Handling Patterns — Better Stack](https://betterstack.com/community/guides/scaling-nodejs/error-handling-express/)
- [Joi vs Zod: Choosing the Right Validation Library](https://betterstack.com/community/guides/scaling-nodejs/joi-vs-zod/)
- [Measuring Requests Duration in Node.js — ipirozhenko](https://ipirozhenko.com/blog/measuring-requests-duration-nodejs-express/)
- [Node.js High-Precision Timing Best Practices — Leapcell](https://leapcell.medium.com/node-js-high-precision-timing-best-practices-d6525107016c)
- [How to Structure an Express.js REST API — Treblle](https://treblle.com/blog/egergr)
