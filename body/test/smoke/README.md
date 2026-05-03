# Smoke Test Harness

## Overview

The smoke test harness under `body/test/smoke/` automates the full Phase-2 acceptance gate for the Minecraft Agent body server. It starts a real Minecraft server and the body server, waits for both to become ready, runs six per-tool scenarios against the live `/execute` endpoint (chat, get_bot_status, navigate, place_block, mine, craft), tears everything down idempotently, and reports PASS/FAIL with a JSON artifact at `body/test/smoke/results/last-run.json`. The same lifecycle module powers `npm run dev:up` for interactive one-command sessions.

## Prerequisites

- **Java 21** installed and on `$PATH`.
- **Minecraft server** installed at `$MC_SERVER_DIR` (default: `~/minecraft-server`) with a working `start.sh` script.
- **Bot username `agent`** already op'd in `ops.json`, OR let the harness add it automatically (it patches `ops.json` on each run).
- **Node.js 18+** (dev box is v22.18.0; native `fetch` required).
- The body server dependencies installed: `cd body && npm install`.

## Quick Start

```bash
# Full smoke-test run (world reset + start MC + start body + run 6 scenarios + teardown)
npm run test:smoke

# Same, but skip world reset (faster re-runs when the world already exists)
npm run test:smoke:keep

# Interactive session: start MC + body, tail prefixed logs, Ctrl-C to stop
npm run dev:up

# Tear down orphaned processes from a previous dev:up
npm run dev:down
```

## Env Vars

| Variable | Default | Description |
|---|---|---|
| `MC_SERVER_DIR` | `~/minecraft-server` | Path to the Minecraft server directory containing `start.sh`. |
| `BOT_HOST` | `127.0.0.1` | Host the body server binds to. |
| `BOT_PORT` | `3000` | Port the body server listens on. |
| `MC_HOST` | `localhost` | Hostname the Mineflayer bot uses to connect to MC. |
| `MC_PORT` | `25565` | Port the Mineflayer bot connects to. |
| `MC_USERNAME` | `agent` | Minecraft username for the bot. |
| `SMOKE_MC_READY_TIMEOUT_MS` | `120000` | How long to wait for the MC server to log `Done (…s)!`. |
| `SMOKE_BOT_READY_TIMEOUT_MS` | `60000` | How long to wait for the bot to spawn and `/status` to return `bot != null`. |
| `SMOKE_SCENARIO_TIMEOUT_MS` | `60000` | Per-scenario timeout in ms. |
| `KEEP_WORLD` | `false` | Set to `1` or `true` to skip world reset (same as `--keep-world`). |

## CLI Flags

| Flag | Description |
|---|---|
| `--keep-world` | Skip world reset (do not delete `world/`, `world_nether/`, `world_the_end/`). |
| `--force-kill` | Kill orphaned processes found in `.pids` before starting a new run. |
| `--dry-run` | Load config and scenarios, print a one-line summary, exit 0. Does not spawn anything. |
| `--down` | (`dev-up.js` only) Send stop signals to processes from the PID file; exit 0. |
| `--help`, `-h` | Print usage text and exit 0. |

## Troubleshooting

### Orphan processes (`--force-kill`)

If a previous run crashed without cleanup, `results/.pids` may contain live PIDs. The harness detects this and refuses to start unless you pass `--force-kill`:

```bash
npm run test:smoke -- --force-kill
```

Or manually kill them and delete `body/test/smoke/results/.pids`.

### World reset (delete-and-regenerate semantics)

By default each run deletes `world/`, `world_nether/`, and `world_the_end/` so the MC server generates a fresh world. If you want to preserve the world between runs:

```bash
npm run test:smoke:keep
# or
KEEP_WORLD=1 npm run test:smoke
```

Note: some scenarios (T4 place_block, T5 mine) depend on a clean world state. Running with `--keep-world` after prior runs may cause scenario failures if blocks from prior runs are left behind.

### Port conflicts

If port 3000 (body server) or 25565 (MC) is already in use:

1. Check for orphaned processes: `pgrep -fl server.jar` and `pgrep -fl 'node src/server.js'`.
2. Use `--force-kill` or kill the processes manually.
3. Override ports via env vars: `BOT_PORT=3001 npm run test:smoke`.

### MC server won't start

- Verify `$MC_SERVER_DIR/start.sh` is executable: `chmod +x ~/minecraft-server/start.sh`.
- Ensure the `eula.txt` in the server directory contains `eula=true`.
- Check Java version: `java -version` should show 21+.
