// Entry point for npm run test:smoke.
// Orchestrates the full smoke-test lifecycle.

const path = require('node:path');
const { loadConfig, printHelp } = require('./config');
const { createClient } = require('./http-client');
const { runAll, printTable, writeJson } = require('./runner');
const { resetWorld, ensureBotIsOp } = require('./world-reset');
const lifecycle = require('./lifecycle');

const RESULTS_DIR = path.join(__dirname, 'results');
const PID_FILE = path.join(RESULTS_DIR, '.pids');
const LAST_RUN_JSON = path.join(RESULTS_DIR, 'last-run.json');

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

  // --dry-run: load modules and report without spawning anything
  if (config.dryRun) {
    const scenarios = require('./scenarios');
    require('./lifecycle'); // just load it to verify it imports cleanly

    const state = {};
    lifecycle.registerSignalHandlers(state);

    if (!Array.isArray(scenarios) || scenarios.length !== 6) {
      throw new Error(`dry-run: expected 6 scenarios, got ${Array.isArray(scenarios) ? scenarios.length : typeof scenarios}`);
    }

    console.log('dry run OK: 6 scenarios discovered, lifecycle module loaded');
    process.exit(0);
  }

  const state = { mcProc: null, bodyProc: null, pidFile: PID_FILE, cleaned: false };
  lifecycle.registerSignalHandlers(state);

  // PID-file check: detect orphaned processes
  const existingPids = await lifecycle.readPidFile(PID_FILE);
  if (existingPids) {
    const mcAlive   = existingPids.mc   ? lifecycle.isAlive(existingPids.mc)   : false;
    const bodyAlive = existingPids.body ? lifecycle.isAlive(existingPids.body) : false;

    if (mcAlive || bodyAlive) {
      if (!config.forceKill) {
        console.error(
          `[run] Found live PIDs in ${PID_FILE} (mc=${existingPids.mc}, body=${existingPids.body}). ` +
          'Use --force-kill to terminate them before running.'
        );
        process.exit(1);
      }

      console.warn('[run] --force-kill: sending SIGTERM to orphaned processes...');
      if (mcAlive)   try { process.kill(existingPids.mc,   'SIGTERM'); } catch (_) {}
      if (bodyAlive) try { process.kill(existingPids.body, 'SIGTERM'); } catch (_) {}
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  }

  try {
    // World reset
    if (!config.keepWorld) {
      await resetWorld(config.mcServerDir);
    }
    await ensureBotIsOp(config.mcServerDir, config.mcUsername);

    // Start MC server and wait for "Done" log line
    const { proc: mcProc, logStream: _mcLog } = lifecycle.startMc(config);
    state.mcProc = mcProc;
    await lifecycle.writePidFile(PID_FILE, { mc: mcProc.pid, body: 0 });

    console.log('[run] Waiting for MC server to be ready...');
    await lifecycle.waitForLog(mcProc, /Done \([0-9.]+s\)!/, config.mcReadyTimeoutMs);
    console.log('[run] MC server is ready');

    // Start body server and wait for bot spawn + status probe
    const { proc: bodyProc, logStream: _bodyLog } = lifecycle.startBody(config);
    state.bodyProc = bodyProc;
    await lifecycle.writePidFile(PID_FILE, { mc: mcProc.pid, body: bodyProc.pid });

    const client = createClient({
      host: config.botHost,
      port: config.botPort,
      timeoutMs: config.scenarioTimeoutMs,
    });

    console.log('[run] Waiting for body server and bot to be ready...');
    await Promise.all([
      lifecycle.waitForLog(bodyProc, /\[Bot\] Spawned in world/, config.botReadyTimeoutMs),
      lifecycle.pollStatus(client, config.botReadyTimeoutMs),
    ]);
    console.log('[run] Body server and bot are ready');

    // Capture spawn anchor
    const spawnEnv = await client.execute('get_bot_status', {});
    const spawnPos = spawnEnv.data ? spawnEnv.data.position : { x: 0, y: 64, z: 0 };

    const runId = Date.now().toString(36);
    const ctx = {
      client,
      config,
      spawn: spawnPos,
      runId,
    };

    // Run scenarios
    const scenarios = require('./scenarios');
    const { allPassed, results } = await runAll(scenarios, ctx);

    // Post-suite cleanup: remove dropped items (best-effort)
    try {
      await client.execute('chat', { message: '/kill @e[type=item]' });
    } catch (err) {
      console.warn(`[run] Post-suite cleanup warning: ${err.message}`);
    }

    // Report
    printTable(results);
    await writeJson(results, LAST_RUN_JSON);
    console.log(`[run] Results written to ${LAST_RUN_JSON}`);

    process.exitCode = allPassed ? 0 : 1;
  } finally {
    await lifecycle.cleanup(state);
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error('[run] Fatal error:', err);
    process.exit(1);
  });
}

module.exports = { main };
