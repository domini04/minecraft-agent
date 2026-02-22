# Phase 1: HTTP Bridge — Component Overview

**Purpose**: Establish communication between the Brain (Python) and Body (Node.js) via HTTP.

---

## What Is the HTTP Bridge?

The HTTP Bridge is the communication layer that allows two separate processes to work together:

| Process | Language | Role |
|---------|----------|------|
| **Brain** | Python | Decides *what* to do (planning, LLM reasoning) |
| **Body** | Node.js | Executes *how* to do it (Minecraft interaction) |

They communicate via **synchronous HTTP requests**:
- Brain sends a command → Body executes it → Body returns the result
- The Brain waits (blocks) until the Body responds

---

## Why HTTP?

| Alternative | Why Not |
|-------------|---------|
| **Same process** | Python can't run Mineflayer (Node.js library) |
| **WebSockets** | Adds complexity; we don't need real-time push from Body to Brain |
| **gRPC** | Overkill for this use case; HTTP is simpler to debug |
| **Message queue** | Adds infrastructure; synchronous is sufficient for our needs |

HTTP is simple, debuggable (curl, Postman), and sufficient for our request-response pattern.

---

## Data Flow

```
┌─────────────────┐                    ┌─────────────────┐                    ┌─────────────────┐
│                 │                    │                 │                    │                 │
│  Python Brain   │                    │  Express Server │                    │    Minecraft    │
│  (LangGraph)    │                    │  (Node.js)      │                    │    Server       │
│                 │                    │                 │                    │                 │
└────────┬────────┘                    └────────┬────────┘                    └────────┬────────┘
         │                                      │                                      │
         │  1. HTTP POST /execute               │                                      │
         │  {tool: "mine", params: {...}}       │                                      │
         │ ──────────────────────────────────>  │                                      │
         │                                      │                                      │
         │                                      │  2. Mineflayer executes action       │
         │                                      │ ──────────────────────────────────>  │
         │                                      │                                      │
         │                                      │  3. World updates / items collected  │
         │                                      │ <──────────────────────────────────  │
         │                                      │                                      │
         │  4. HTTP Response                    │                                      │
         │  {success: true, data: {...}}        │                                      │
         │ <──────────────────────────────────  │                                      │
         │                                      │                                      │
```

### Step-by-Step

1. **Brain sends command**: Python makes an HTTP POST request with the tool name and parameters
2. **Body executes**: Express receives the request, calls the appropriate Mineflayer function
3. **Minecraft responds**: The bot performs the action, world state changes, bot observes results
4. **Body returns result**: Express sends back a JSON response with success/failure and data

---

## Components

### Express Server (The Body's API Layer)

**Location**: `body/src/`

**Responsibilities**:
- Listen for HTTP requests on a configured port
- Parse incoming JSON commands
- Route to appropriate Mineflayer functions
- Wait for actions to complete
- Return structured JSON responses

**Key routes**:
| Route | Method | Purpose |
|-------|--------|---------|
| `/status` | GET | Health check + bot state |
| `/execute` | POST | Execute a tool command |

---

## API Contract

### Design Style: RPC

We use **RPC-style** routing — a single `/execute` endpoint with the tool name in the request body. This matches LangChain's tool-calling pattern and simplifies routing.

### Request Format

```json
{
  "tool": "mine",
  "params": {
    "target": "oak_log",
    "count": 5
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Tool name to execute |
| `params` | object | Tool-specific parameters |

### Response Format

**Success**:
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

**Error**:
```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "No oak_log found within search radius",
    "context": {
      "target": "oak_log",
      "search_radius": 64
    }
  },
  "tool": "mine",
  "duration_ms": 1250
}
```

### Error Codes

| Code | When |
|------|------|
| `RESOURCE_NOT_FOUND` | Block/entity not found nearby |
| `PATH_BLOCKED` | Pathfinder can't reach target |
| `INSUFFICIENT_MATERIALS` | Missing items for craft |
| `INVENTORY_FULL` | Can't pick up items |
| `INVALID_PARAMS` | Bad input to tool |
| `ACTION_FAILED` | Generic action failure |
| `TIMEOUT` | Action took too long |
| `BOT_DIED` | Bot died during action |
| `DISCONNECTED` | Lost connection to server |

### HTTP Status Codes

| Situation | HTTP Status |
|-----------|-------------|
| Valid tool call (success or failure) | 200 OK |
| Malformed JSON | 400 Bad Request |
| Unknown route | 404 Not Found |
| Server crash | 500 Internal Server Error |

Tool failures return 200 with `success: false` — HTTP errors are reserved for protocol issues.

### Content-Type

- **Format**: JSON only (`application/json`)
- **Validation**: Lenient — parse as JSON regardless of header, log warning if unexpected

```javascript
// Express setup
app.use(express.json());

// Optional: warn on unexpected Content-Type
app.use((req, res, next) => {
  if (req.method === 'POST' && !req.is('application/json')) {
    console.warn(`Unexpected Content-Type: ${req.headers['content-type']}`);
  }
  next();
});
```

### Authentication & Network Binding

- **Default**: Bind to `127.0.0.1` (localhost only)
- **Configurable**: Via `BOT_HOST` env var for cloud deployment

```javascript
const HOST = process.env.BOT_HOST || '127.0.0.1';
const PORT = process.env.BOT_PORT || 3000;

app.listen(PORT, HOST, () => {
  console.log(`Body listening on ${HOST}:${PORT}`);
});
```

| Deployment | BOT_HOST | Security |
|------------|----------|----------|
| Local dev | (default) `127.0.0.1` | Port unreachable from network |
| Single VM | (default) `127.0.0.1` | Same as local |
| Cloud Run / GKE | `0.0.0.0` | Add API key middleware |

---

## Timeout Handling

### The Problem

Mineflayer has no built-in timeout — actions wait indefinitely. We implement timeouts in Express to prevent hangs.

### Timeout Strategy

```
Action timeout (Express):  4 minutes  ← Body gives up first
Client timeout (Python):   5 minutes  ← 1-minute buffer
```

If action exceeds 4 minutes, Express returns:
```json
{
  "success": false,
  "error": {
    "code": "TIMEOUT",
    "message": "Action timed out after 4 minutes"
  }
}
```

This ensures Brain and Body stay synchronized — Brain always receives a response.

### Timeout Flow

```
Python Brain              Express (our code)              Mineflayer
     │                          │                             │
     │  POST /execute           │                             │
     │ ───────────────────────> │                             │
     │                          │  Start 4-min timer          │
     │                          │  Call Mineflayer action     │
     │                          │ ──────────────────────────> │
     │  (waiting, up to 5m)     │  (waiting, up to 4m)       │
     │                          │                             │
     │                          │  Timer fires OR action done │
     │ <─────────────────────── │                             │
     │  Response (success/fail) │                             │
```

---

### Mineflayer Bot

**Library**: [mineflayer](https://github.com/PrismarineJS/mineflayer)

**Responsibilities**:
- Maintain persistent connection to Minecraft server
- Execute actions: move, mine, craft, place, chat
- Observe world: nearby blocks, entities, inventory
- Report results back to Express

### Python Client (Brain's HTTP Layer)

**Location**: `brain/src/`

**Responsibilities**:
- Send HTTP requests to Express server
- Handle timeouts (long-running actions like mining)
- Parse JSON responses
- Surface errors to the LangGraph agent

---

## Why Synchronous?

The Brain sends a command and **waits** for it to complete. This is intentional:

1. **Simplicity**: No need to poll for completion or manage async state
2. **Natural fit**: LangGraph nodes execute sequentially; blocking is fine
3. **Easy debugging**: Request in → response out, easy to trace

**Trade-off**: Long actions (mining 64 blocks) block the Brain. We handle this with generous timeouts (~5 minutes). If this becomes a problem, we can add async polling later.

---

## Configuration

| Setting | Default | Purpose |
|---------|---------|---------|
| `BODY_PORT` | 3000 | Express server port |
| `BODY_HOST` | localhost | Express server host |
| `MC_HOST` | localhost | Minecraft server host |
| `MC_PORT` | 25565 | Minecraft server port |
| `MC_USERNAME` | bot | Bot's in-game name |
| `ACTION_TIMEOUT_MS` | 240000 | Action timeout in Express (4 min) |
| `CLIENT_TIMEOUT_MS` | 300000 | Client timeout in Python (5 min) |

---

## Phase 1 Completion Criteria

| Step | Test | Pass Condition |
|------|------|----------------|
| 1.1 | `curl localhost:3000/status` | Returns `{ok: true}` |
| 1.2 | Start bot, check Minecraft | Bot appears in-game |
| 1.3 | `curl localhost:3000/status` | Returns `{health, position, food}` |
| 1.4 | Run Python script | Prints bot status |
| 1.5 | `curl -X POST localhost:3000/execute` | Returns `{success: false, error: "not implemented"}` |
| 1.6 | Run test suite | All tests pass |
