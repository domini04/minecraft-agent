// Entry point for npm run dev:up (and npm run dev:down via --down flag).
// Starts MC server + body server and tails combined logs with prefixed output.

const path = require('node:path');
const readline = require('node:readline');
const { loadConfig, printHelp } = require('./config');
const { createClient } = require('./http-client');
const { resetWorld, ensureBotIsOp } = require('./world-reset');
const lifecycle = require('./lifecycle');

const RESULTS_DIR = path.join(__dirname, 'results');
const PID_FILE = path.join(RESULTS_DIR, '.pids');

/**
 * Pipes lines from a readline interface to stdout with a prefix.
 * @param {readline.Interface} rl
 * @param {string} prefix
 */
function pipeWithPrefix(rl, prefix) {
  rl.on('line', (line) => {
    process.stdout.write(`${prefix} ${line}\n`);
  });
}

/**
 * Main entry point.
 * @param {string[]} argv
 */
async function main(argv = process.argv.slice(2)) {
  const config = loadConfig(argv);

  // --help
  if (config.help) {
    printHelp(process.stdout);
    process.exit(0);
  }

  // --down: tear down running instances from PID file
  if (config.down) {
    const pids = await lifecycle.readPidFile(PID_FILE);
    if (!pids) {
      console.log('[dev-up] No PID file found; nothing to stop.');
      process.exit(0);
    }

    console.log(`[dev-up] Sending stop to MC (pid=${pids.mc}) and SIGTERM to body (pid=${pids.body})...`);

    if (pids.body && lifecycle.isAlive(pids.body)) {
      try { process.kill(pids.body, 'SIGTERM'); } catch (_) {}
    }

    if (pids.mc && lifecycle.isAlive(pids.mc)) {
      // For standalone --down we can only send SIGTERM; the stdin pipe is gone
      try { process.kill(pids.mc, 'SIGTERM'); } catch (_) {}
    }

    await new Promise((resolve) => setTimeout(resolve, 5000));

    // Remove PID file
    const fs = require('node:fs/promises');
    try { await fs.unlink(PID_FILE); } catch (_) {}
    console.log('[dev-up] Down complete.');
    process.exit(0);
  }

  const state = { mcProc: null, bodyProc: null, pidFile: PID_FILE, cleaned: false };
  lifecycle.registerSignalHandlers(state);

  try {
    // World reset (unless --keep-world)
    if (!config.keepWorld) {
      await resetWorld(config.mcServerDir);
    }
    await ensureBotIsOp(config.mcServerDir, config.mcUsername);

    // Start MC server
    const { proc: mcProc, logStream: mcLog } = lifecycle.startMc(config);
    state.mcProc = mcProc;
    await lifecycle.writePidFile(PID_FILE, { mc: mcProc.pid, body: 0 });

    // Pipe MC logs with prefix [mc]
    pipeWithPrefix(mcLog, '[mc]');

    console.log('[dev-up] Waiting for MC server to be ready...');
    await lifecycle.waitForLog(mcProc, /Done \([0-9.]+s\)!/, config.mcReadyTimeoutMs);
    console.log('[dev-up] MC server is ready');

    // Start body server
    const { proc: bodyProc, logStream: bodyLog } = lifecycle.startBody(config);
    state.bodyProc = bodyProc;
    await lifecycle.writePidFile(PID_FILE, { mc: mcProc.pid, body: bodyProc.pid });

    // Pipe body logs with prefix [body]
    pipeWithPrefix(bodyLog, '[body]');

    const client = createClient({
      host: config.botHost,
      port: config.botPort,
      timeoutMs: 30000,
    });

    console.log('[dev-up] Waiting for body server and bot to be ready...');
    await Promise.all([
      lifecycle.waitForLog(bodyProc, /\[Bot\] Spawned in world/, config.botReadyTimeoutMs),
      lifecycle.pollStatus(client, config.botReadyTimeoutMs),
    ]);

    console.log('[dev-up] Ready! Press Ctrl-C to stop.');
    console.log(`[dev-up] Body server: http://${config.botHost}:${config.botPort}`);

    // Block until SIGINT / process death
    await new Promise((resolve) => {
      mcProc.once('exit', resolve);
      bodyProc.once('exit', resolve);
    });
  } finally {
    await lifecycle.cleanup(state);
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error('[dev-up] Fatal error:', err);
    process.exit(1);
  });
}

module.exports = { main };
