// Lifecycle management for the smoke test harness.
// Shared by run.js (automated test) and dev-up.js (interactive session).

const { spawn } = require('node:child_process');
const readline = require('node:readline');
const fs = require('node:fs/promises');
const path = require('node:path');

/**
 * Spawns the Minecraft server via start.sh.
 *
 * @param {object} config
 * @returns {{ proc: ChildProcess, logStream: readline.Interface }}
 */
function startMc(config) {
  const proc = spawn(path.join(config.mcServerDir, 'start.sh'), [], {
    cwd: config.mcServerDir,
    stdio: ['pipe', 'pipe', 'pipe'],
    detached: false,
  });

  const logStream = readline.createInterface({ input: proc.stdout, crlfDelay: Infinity });
  const errStream = readline.createInterface({ input: proc.stderr, crlfDelay: Infinity });

  errStream.on('line', (line) => {
    process.stderr.write(`[mc] ${line}\n`);
  });

  proc.on('error', (err) => {
    console.error(`[lifecycle] MC server process error: ${err.message}`);
  });

  return { proc, logStream };
}

/**
 * Spawns the body server via node src/server.js from the body/ directory.
 *
 * @param {object} config
 * @returns {{ proc: ChildProcess, logStream: readline.Interface }}
 */
function startBody(config) {
  // Resolve the body/ directory relative to this file (body/test/smoke/lifecycle.js → body/)
  const bodyDir = path.resolve(__dirname, '..', '..');

  const env = {
    ...process.env,
    BOT_HOST: config.botHost,
    BOT_PORT: String(config.botPort),
    MC_HOST: config.mcHost,
    MC_PORT: String(config.mcPort),
    MC_USERNAME: config.mcUsername,
  };

  const proc = spawn('node', ['src/server.js'], {
    cwd: bodyDir,
    stdio: ['pipe', 'pipe', 'pipe'],
    env,
    detached: false,
  });

  const logStream = readline.createInterface({ input: proc.stdout, crlfDelay: Infinity });
  const errStream = readline.createInterface({ input: proc.stderr, crlfDelay: Infinity });

  errStream.on('line', (line) => {
    process.stderr.write(`[body] ${line}\n`);
  });

  proc.on('error', (err) => {
    console.error(`[lifecycle] Body server process error: ${err.message}`);
  });

  return { proc, logStream };
}

/**
 * Waits for the first line matching regex on proc's stdout.
 * Uses node:readline over proc.stdout for line-buffered tailing.
 *
 * @param {ChildProcess} proc
 * @param {RegExp} regex
 * @param {number} timeoutMs
 * @returns {Promise<string>} The matching line
 */
function waitForLog(proc, regex, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer;

    const rl = readline.createInterface({ input: proc.stdout, crlfDelay: Infinity });

    function cleanup() {
      clearTimeout(timer);
      rl.close();
    }

    timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        cleanup();
        reject(new Error(`waitForLog: timed out after ${timeoutMs}ms waiting for ${regex}`));
      }
    }, timeoutMs);

    rl.on('line', (line) => {
      // Echo all lines
      process.stdout.write(`[proc] ${line}\n`);
      if (!settled && regex.test(line)) {
        settled = true;
        cleanup();
        resolve(line);
      }
    });

    rl.on('close', () => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error('waitForLog: process stdout closed without matching log line'));
      }
    });

    proc.on('exit', (code) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        rl.close();
        reject(new Error(`waitForLog: process exited with code ${code} before log matched`));
      }
    });
  });
}

/**
 * Polls GET /status until bot != null, then resolves.
 * Rejects on timeout.
 *
 * @param {object} client - http-client instance
 * @param {number} timeoutMs
 * @param {number} [intervalMs=500]
 * @returns {Promise<void>}
 */
function pollStatus(client, timeoutMs, intervalMs = 500) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    let timer;

    async function attempt() {
      try {
        const data = await client.status();
        if (data && data.bot != null) {
          resolve(data);
          return;
        }
      } catch (_) {
        // Server not up yet; retry
      }

      if (Date.now() >= deadline) {
        reject(new Error(`pollStatus: timed out after ${timeoutMs}ms waiting for bot != null`));
        return;
      }

      timer = setTimeout(attempt, intervalMs);
    }

    attempt();

    // Ensure we don't leak the timer on reject/resolve path
    // (cleanup happens naturally when Promise settles and attempt() returns early)
    void timer; // suppress lint warning
  });
}

/**
 * Returns true if the process with the given PID is alive (kill -0).
 * Returns false if ESRCH (no such process).
 *
 * @param {number} pid
 * @returns {boolean}
 */
function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    if (err.code === 'ESRCH') return false;
    // EPERM: process exists but we can't signal it
    return err.code === 'EPERM';
  }
}

/**
 * Writes a PID file.
 *
 * @param {string} pidFile
 * @param {{ mc: number, body: number }} pids
 */
async function writePidFile(pidFile, { mc, body }) {
  await fs.mkdir(path.dirname(pidFile), { recursive: true });
  await fs.writeFile(pidFile, JSON.stringify({ mc, body }), 'utf8');
}

/**
 * Reads a PID file.
 *
 * @param {string} pidFile
 * @returns {Promise<{mc: number, body: number}|null>}
 */
async function readPidFile(pidFile) {
  try {
    const raw = await fs.readFile(pidFile, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Sends SIGTERM to a process and waits up to graceMs before SIGKILL.
 * @param {ChildProcess} proc
 * @param {number} graceMs
 * @returns {Promise<void>}
 */
function gracefulKill(proc, graceMs) {
  return new Promise((resolve) => {
    if (!proc || proc.exitCode !== null || proc.killed) {
      resolve();
      return;
    }

    const timer = setTimeout(() => {
      try { proc.kill('SIGKILL'); } catch (_) {}
      resolve();
    }, graceMs);

    proc.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });

    try {
      proc.kill('SIGTERM');
    } catch (err) {
      clearTimeout(timer);
      resolve();
    }
  });
}

/**
 * Idempotent cleanup. Never throws.
 * state = { mcProc, bodyProc, pidFile, cleaned? }
 *
 * @param {object} state
 */
async function cleanup(state) {
  if (!state || state.cleaned) return;
  state.cleaned = true;

  console.log('[lifecycle] Cleanup starting...');

  // Terminate body server: SIGTERM + 5s grace, then SIGKILL
  if (state.bodyProc) {
    try {
      await gracefulKill(state.bodyProc, 5000);
      console.log('[lifecycle] Body server stopped');
    } catch (err) {
      console.error(`[lifecycle] Error stopping body server: ${err.message}`);
    }
  }

  // Terminate MC server: send 'stop\n' via stdin, 15s grace, then SIGKILL
  if (state.mcProc) {
    try {
      if (state.mcProc.stdin && !state.mcProc.stdin.destroyed) {
        state.mcProc.stdin.write('stop\n');
      }
      await gracefulKill(state.mcProc, 15000);
      console.log('[lifecycle] MC server stopped');
    } catch (err) {
      console.error(`[lifecycle] Error stopping MC server: ${err.message}`);
    }
  }

  // Remove PID file
  if (state.pidFile) {
    try {
      await fs.unlink(state.pidFile);
    } catch (err) {
      if (err.code !== 'ENOENT') {
        console.error(`[lifecycle] Error removing PID file: ${err.message}`);
      }
    }
  }

  console.log('[lifecycle] Cleanup complete');
}

/**
 * Registers SIGINT, SIGTERM, uncaughtException, unhandledRejection, and 'exit'
 * to call cleanup(state). Idempotent via a flag on the state object.
 *
 * @param {object} state
 */
function registerSignalHandlers(state) {
  if (state._handlersRegistered) return;
  state._handlersRegistered = true;

  const doCleanup = async () => {
    await cleanup(state);
  };

  process.on('SIGINT',  () => { doCleanup().finally(() => process.exit(0)); });
  process.on('SIGTERM', () => { doCleanup().finally(() => process.exit(0)); });

  process.on('uncaughtException', (err) => {
    console.error('[lifecycle] Uncaught exception:', err);
    doCleanup().finally(() => process.exit(1));
  });

  process.on('unhandledRejection', (reason) => {
    console.error('[lifecycle] Unhandled rejection:', reason);
    doCleanup().finally(() => process.exit(1));
  });

  process.on('exit', () => {
    // Synchronous best-effort: send stop/SIGKILL; can't await here
    if (state && !state.cleaned) {
      if (state.bodyProc && !state.bodyProc.killed) {
        try { state.bodyProc.kill('SIGKILL'); } catch (_) {}
      }
      if (state.mcProc && !state.mcProc.killed) {
        try { state.mcProc.stdin && state.mcProc.stdin.write('stop\n'); } catch (_) {}
        try { state.mcProc.kill('SIGKILL'); } catch (_) {}
      }
    }
  });
}

module.exports = {
  startMc,
  startBody,
  waitForLog,
  pollStatus,
  cleanup,
  registerSignalHandlers,
  writePidFile,
  readPidFile,
  isAlive,
};
