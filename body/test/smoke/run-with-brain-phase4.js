// run-with-brain-phase4.js — Phase 4 acceptance smoke (live MC + body + Gemini brain).
//
// Mirrors run-with-brain.js lifecycle scaffolding (MC + body spawn, world reset,
// PID-file orphan handling, signal handlers, final cleanup) but:
//   1. Inserts a pre-seed step (give bot 5 oak_logs via op-chat) between
//      "body and bot ready" and the brain CLI call.
//   2. Invokes runPhase4Smoke() (goal="craft 1 oak_planks" --verbose --no-cache).
//   3. Asserts P1–P7 via assertSmokePhase4().
//   4. Writes artifact to last-brain-phase4-run.json (does NOT clobber Phase-3's
//      last-brain-run.json).
//
// Phase-3 entry (run-with-brain.js) is untouched; the two harnesses coexist.
//
// Cost: ~$0.002/run expected (~3 Gemini calls via Gemini 3.1 Flash Lite).
// Do not run in CI loops. One live run per PGE sprint gate (C13).

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const readline = require('node:readline');

const { loadConfig, printHelp } = require('./config');
const { createClient } = require('./http-client');
const { resetWorld, ensureBotIsOp } = require('./world-reset');
const lifecycle = require('./lifecycle');
const {
  runPhase4Smoke,
  resolveBrainPython,
  countOakLogs,
} = require('./brain-scenario');

const RESULTS_DIR = path.join(__dirname, 'results');
const PID_FILE = path.join(RESULTS_DIR, '.pids');
// Separate artifact path — does NOT overwrite Phase-3's last-brain-run.json.
const ARTIFACT_PATH = path.join(RESULTS_DIR, 'last-brain-phase4-run.json');
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const BODY_LOG_BUFFER_SIZE = 200;

/**
 * Print a [brain-smoke-p4]-prefixed line to stdout.
 * @param {string} msg
 */
function log(msg) {
  process.stdout.write(`[brain-smoke-p4] ${msg}\n`);
}

/**
 * Print a [brain-smoke-p4]-prefixed line to stderr.
 * @param {string} msg
 */
function logErr(msg) {
  process.stderr.write(`[brain-smoke-p4] ${msg}\n`);
}

/**
 * Try to populate process.env.GEMINI_API_KEY from <repo>/.env if missing.
 * Never logs the value. Returns true if the key is present (in env or .env).
 *
 * @returns {{present: boolean, source: 'env'|'.env'|'none'}}
 */
function ensureGeminiKey() {
  if (process.env.GEMINI_API_KEY && process.env.GEMINI_API_KEY.trim().length > 0) {
    return { present: true, source: 'env' };
  }
  const envFile = path.join(REPO_ROOT, '.env');
  try {
    const raw = fs.readFileSync(envFile, 'utf8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const m = /^GEMINI_API_KEY\s*=\s*(.*)$/.exec(trimmed);
      if (m) {
        let val = m[1].trim();
        if ((val.startsWith('"') && val.endsWith('"'))
            || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.slice(1, -1);
        }
        if (val.length > 0) {
          process.env.GEMINI_API_KEY = val;
          return { present: true, source: '.env' };
        }
      }
    }
  } catch (_) {
    // .env not present or unreadable — fall through.
  }
  return { present: false, source: 'none' };
}

/**
 * Run preflight checks for the Phase-4 harness.
 * Mirrors the Phase-3 preflight exactly (same 5 checks).
 *
 * @param {object} config
 * @returns {Promise<{ok: boolean, results: object, failures: string[]}>}
 */
async function preflight(config) {
  const results = {
    P1_geminiKey: false,
    P2_venv: false,
    P3_brainHelp: false,
    P4_resultsDir: false,
    P5_pidOrphans: false,
  };
  const failures = [];

  // P1 — GEMINI_API_KEY.
  const keyCheck = ensureGeminiKey();
  results.P1_geminiKey = keyCheck.present;
  if (keyCheck.present) {
    log(`  [OK] P1 GEMINI_API_KEY (source=${keyCheck.source})`);
  } else {
    log('  [FAIL] P1 GEMINI_API_KEY missing (env and .env both empty)');
    failures.push('P1: GEMINI_API_KEY missing');
  }

  // P2 — venv python.
  const py = resolveBrainPython(REPO_ROOT);
  try {
    fs.accessSync(py, fs.constants.X_OK);
    results.P2_venv = true;
    log(`  [OK] P2 brain venv python (${py})`);
  } catch (_) {
    log(`  [FAIL] P2 brain venv python missing or not executable: ${py}`);
    failures.push('P2: brain venv python missing');
  }

  // P3 — `python3 -m src --help` exits 0.
  if (results.P2_venv) {
    const brainCwd = path.join(REPO_ROOT, 'brain');
    const helpRes = spawnSync(py, ['-m', 'src', '--help'], {
      cwd: brainCwd,
      timeout: 10_000,
      encoding: 'utf8',
    });
    if (helpRes.status === 0
        && helpRes.stdout
        && /\bgoal\b/.test(helpRes.stdout)) {
      results.P3_brainHelp = true;
      log('  [OK] P3 python -m src --help (exit 0, contains "goal")');
    } else {
      const tail = (helpRes.stderr || helpRes.stdout || '').slice(0, 500);
      log(`  [FAIL] P3 python -m src --help failed (status=${helpRes.status}): ${tail}`);
      failures.push(`P3: python -m src --help failed (status=${helpRes.status})`);
    }
  } else {
    log('  [FAIL] P3 skipped (P2 failed)');
    failures.push('P3: skipped (P2 failed)');
  }

  // P4 — results directory writable.
  try {
    await fsp.mkdir(RESULTS_DIR, { recursive: true });
    const probe = path.join(RESULTS_DIR, '.write-probe-p4');
    await fsp.writeFile(probe, '');
    await fsp.unlink(probe);
    results.P4_resultsDir = true;
    log(`  [OK] P4 results dir writable (${RESULTS_DIR})`);
  } catch (err) {
    log(`  [FAIL] P4 results dir not writable: ${err.message}`);
    failures.push(`P4: results dir not writable: ${err.message}`);
  }

  // P5 — PID-file orphan check.
  try {
    const existing = await lifecycle.readPidFile(PID_FILE);
    if (!existing) {
      results.P5_pidOrphans = true;
      log('  [OK] P5 no PID file present');
    } else {
      const mcAlive = existing.mc ? lifecycle.isAlive(existing.mc) : false;
      const bodyAlive = existing.body ? lifecycle.isAlive(existing.body) : false;
      if (!mcAlive && !bodyAlive) {
        results.P5_pidOrphans = true;
        log('  [OK] P5 stale PID file only (no live processes)');
      } else if (config.forceKill) {
        results.P5_pidOrphans = true;
        log(`  [OK] P5 live PIDs detected (mc=${existing.mc}, body=${existing.body}) — will be killed by --force-kill`);
      } else {
        log(`  [FAIL] P5 live orphaned PIDs (mc=${existing.mc}, body=${existing.body}); rerun with --force-kill`);
        failures.push('P5: live orphaned PIDs (use --force-kill)');
      }
    }
  } catch (err) {
    log(`  [FAIL] P5 PID check error: ${err.message}`);
    failures.push(`P5: ${err.message}`);
  }

  const ok = failures.length === 0;
  return { ok, results, failures };
}

/**
 * Tap a child stdout/stderr stream into a rolling FIFO buffer of N lines.
 *
 * @param {NodeJS.ReadableStream} stream
 * @param {number} cap
 * @param {string} label
 * @returns {string[]} the buffer (live reference; caller reads at end)
 */
function tapRollingBuffer(stream, cap, label) {
  const buf = [];
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  rl.on('line', (line) => {
    buf.push(`[${label}] ${line}`);
    if (buf.length > cap) buf.shift();
  });
  return buf;
}

/**
 * Write the JSON artifact for this run.
 * @param {object} artifact
 */
async function writeArtifact(artifact) {
  await fsp.mkdir(RESULTS_DIR, { recursive: true });
  await fsp.writeFile(ARTIFACT_PATH, JSON.stringify(artifact, null, 2), 'utf8');
}

async function main(argv = process.argv.slice(2)) {
  const config = loadConfig(argv);

  if (config.help) {
    printHelp(process.stdout);
    process.stdout.write(
      '\n[brain-smoke-p4] Phase 4 multi-step brain live smoke (craft 1 oak_planks).\n'
      + '                 Invokes guide_retriever -> planner -> executor end-to-end.\n'
      + '                 Cost: ~$0.002/run. Iterations: ~3 expected, <=5 enforced.\n'
      + '                 Artifact: test/smoke/results/last-brain-phase4-run.json\n'
      + '                 P1-P7 assertions gate the PASS verdict.\n'
    );
    process.exit(0);
  }

  // --- Preflight ----------------------------------------------------------
  log('Preflight checks:');
  const pre = await preflight(config);
  if (!pre.ok) {
    logErr(`preflight FAIL: ${pre.failures.join('; ')}`);
    process.exit(1);
  }

  if (config.dryRun) {
    log('dry run: preflight passed and modules loaded; not spawning MC/body/brain.');
    log('Phase 4 scenario module loaded OK (runPhase4Smoke, assertSmokePhase4, parseCraftStep).');
    process.exit(0);
  }

  // --- Lifecycle setup ---------------------------------------------------
  const state = { mcProc: null, bodyProc: null, pidFile: PID_FILE, cleaned: false };
  lifecycle.registerSignalHandlers(state);

  // PID-file orphan recovery.
  const existingPids = await lifecycle.readPidFile(PID_FILE);
  if (existingPids) {
    const mcAlive   = existingPids.mc   ? lifecycle.isAlive(existingPids.mc)   : false;
    const bodyAlive = existingPids.body ? lifecycle.isAlive(existingPids.body) : false;
    if (mcAlive || bodyAlive) {
      if (!config.forceKill) {
        logErr(`Found live PIDs in ${PID_FILE} (mc=${existingPids.mc}, body=${existingPids.body}). Use --force-kill.`);
        process.exit(1);
      }
      log('--force-kill: sending SIGTERM to orphaned processes...');
      if (mcAlive)   try { process.kill(existingPids.mc,   'SIGTERM'); } catch (_) {}
      if (bodyAlive) try { process.kill(existingPids.body, 'SIGTERM'); } catch (_) {}
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  }

  let bodyLogBuffer = [];
  let brainResult = null;
  let verdict = 'FAIL';
  let failureReasons = [];
  const t0 = Date.now();

  // Client is declared here so it's accessible in the finally block for
  // the optional post-run inventory log.
  let client = null;
  let preSeedOakLogs = 0;

  try {
    if (!config.keepWorld) {
      await resetWorld(config.mcServerDir);
    }
    await ensureBotIsOp(config.mcServerDir, config.mcUsername);

    // MC server.
    const { proc: mcProc } = lifecycle.startMc(config);
    state.mcProc = mcProc;
    await lifecycle.writePidFile(PID_FILE, { mc: mcProc.pid, body: 0 });

    log('Waiting for MC server to be ready...');
    await lifecycle.waitForLog(mcProc, /Done \([0-9.]+s\)!/, config.mcReadyTimeoutMs);
    log('MC server is ready');

    // Body server.
    const { proc: bodyProc } = lifecycle.startBody(config);
    state.bodyProc = bodyProc;
    await lifecycle.writePidFile(PID_FILE, { mc: mcProc.pid, body: bodyProc.pid });

    bodyLogBuffer = tapRollingBuffer(bodyProc.stdout, BODY_LOG_BUFFER_SIZE, 'body');

    client = createClient({
      host: config.botHost,
      port: config.botPort,
      timeoutMs: config.scenarioTimeoutMs,
    });

    log('Waiting for body server and bot to be ready...');
    await Promise.all([
      lifecycle.waitForLog(bodyProc, /\[Bot\] Spawned in world/, config.botReadyTimeoutMs),
      lifecycle.pollStatus(client, config.botReadyTimeoutMs),
    ]);
    log('Body server and bot are ready');

    // --- Pre-seed inventory -----------------------------------------------
    // Issue /give command as an opped bot, wait one tick, then verify.
    log(`Pre-seeding inventory: /give ${config.mcUsername} oak_log 5`);
    const giveResp = await client.execute('chat', { message: `/give ${config.mcUsername} oak_log 5` });
    if (!giveResp.success) {
      throw new Error(`[brain-smoke-p4] pre-seed give failed: ${JSON.stringify(giveResp.error || giveResp)}`);
    }

    // Give the server a tick to apply the command before reading inventory.
    await new Promise((r) => setTimeout(r, 1500));

    const statusResp = await client.execute('get_bot_status', {});
    if (!statusResp.success) {
      throw new Error(`[brain-smoke-p4] pre-seed status check failed: ${JSON.stringify(statusResp.error || statusResp)}`);
    }
    preSeedOakLogs = countOakLogs(statusResp.data);
    if (preSeedOakLogs < 1) {
      throw new Error(`[brain-smoke-p4] pre-seed verification failed: oak_log count=${preSeedOakLogs} after /give`);
    }
    log(`Pre-seed verified: bot has ${preSeedOakLogs} oak_log(s) in inventory`);

    // --- Brain scenario ---------------------------------------------------
    const runId = Date.now().toString(36);
    log(`Running Phase-4 brain CLI smoke (runId=${runId}); cost ~$0.002 (~3 Gemini calls).`);
    brainResult = await runPhase4Smoke({
      client,
      config,
      runId,
    });

    verdict = brainResult.verdict;
    failureReasons = brainResult.reasons;

    if (verdict === 'PASS') {
      log(`VERDICT: PASS (iterations=${brainResult.iterationCount}, durationMs=${brainResult.durationMs})`);
    } else {
      logErr(`VERDICT: FAIL — ${failureReasons.join(' | ')}`);
    }
  } catch (err) {
    verdict = 'FAIL';
    failureReasons.push(`harness error: ${err.message}`);
    logErr(`harness error: ${err.stack || err.message}`);
  } finally {
    // Optional post-run inventory log (informational, not gating per plan §A4).
    if (client) {
      try {
        const postStatus = await client.execute('get_bot_status', {});
        if (postStatus.success) {
          const planksArr = (postStatus.data && Array.isArray(postStatus.data.inventory))
            ? postStatus.data.inventory.filter((i) => i && i.name === 'oak_planks')
            : [];
          const planksCount = planksArr.reduce((s, i) => s + (i.count || 0), 0);
          log(`Post-run inventory: oak_planks=${planksCount} (informational)`);
        }
      } catch (_) {
        // Body may already be shutting down — ignore.
      }
    }

    // Build artifact BEFORE cleanup so we capture body log buffer state.
    const artifact = {
      schemaVersion: 1,
      scenario: 'phase4-craft-oak-planks',
      timestamp: new Date().toISOString(),
      verdict,
      durationMs: Date.now() - t0,
      preflight: pre ? {
        geminiKeyPresent: pre.results.P1_geminiKey,
        venvOk: pre.results.P2_venv,
        helpExitCode: pre.results.P3_brainHelp ? 0 : null,
        resultsDirOk: pre.results.P4_resultsDir,
        pidOrphansOk: pre.results.P5_pidOrphans,
      } : null,
      preSeed: {
        oakLogsGiven: 5,
        oakLogsVerified: preSeedOakLogs,
      },
      brain: brainResult ? {
        command: brainResult.command,
        cwd: brainResult.cwd,
        exitCode: brainResult.exitCode,
        durationMs: brainResult.durationMs,
        stdout: brainResult.stdout,
        stderr: brainResult.stderr,
        iterations: brainResult.iterationCount,
        steps: brainResult.stepsCount,
        finalResultLine: brainResult.finalResultLine,
        craftStepData: brainResult.craftStepData,
      } : null,
      phase4Assertions: brainResult ? brainResult.assertions : null,
      bodyLogExcerpt: bodyLogBuffer.slice(-BODY_LOG_BUFFER_SIZE),
      failureReasons,
    };
    try {
      await writeArtifact(artifact);
      log(`Artifact written: ${ARTIFACT_PATH}`);
    } catch (artErr) {
      logErr(`failed to write artifact: ${artErr.message}`);
    }

    await lifecycle.cleanup(state);
  }

  process.exitCode = verdict === 'PASS' ? 0 : 1;
}

if (require.main === module) {
  main().catch((err) => {
    logErr(`Fatal error: ${err.stack || err.message}`);
    process.exit(1);
  });
}

module.exports = { main, preflight };
