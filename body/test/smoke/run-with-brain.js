// run-with-brain.js — Phase 3 acceptance smoke (live MC + body + Gemini brain).
//
// Sprint 3i. Mirrors run.js's lifecycle scaffolding (MC + body spawn, world
// reset, PID-file orphan handling, signal handlers, final cleanup) but
// replaces the 6-scenario runner with a single call to runBrainSmoke() in
// brain-scenario.js.
//
// Cost: ~2 Gemini API calls per run. Do not loop. PGE max-iterations=3.

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const readline = require('node:readline');

const { loadConfig, printHelp } = require('./config');
const { createClient } = require('./http-client');
const { resetWorld, ensureBotIsOp } = require('./world-reset');
const lifecycle = require('./lifecycle');
const { runBrainSmoke, resolveBrainPython } = require('./brain-scenario');

const RESULTS_DIR = path.join(__dirname, 'results');
const PID_FILE = path.join(RESULTS_DIR, '.pids');
const ARTIFACT_PATH = path.join(RESULTS_DIR, 'last-brain-run.json');
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const BODY_LOG_BUFFER_SIZE = 200;

/**
 * Print a [brain-smoke]-prefixed line to stdout.
 * @param {string} msg
 */
function log(msg) {
  process.stdout.write(`[brain-smoke] ${msg}\n`);
}

/**
 * Print a [brain-smoke]-prefixed line to stderr.
 * @param {string} msg
 */
function logErr(msg) {
  process.stderr.write(`[brain-smoke] ${msg}\n`);
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
        // Strip optional quotes.
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
 * Run the 5 preflight checks described in plan §3.
 * Returns an object whose `ok` field is true iff all required checks pass.
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
    log(`  [✓] P1 GEMINI_API_KEY (source=${keyCheck.source})`);
  } else {
    log('  [✗] P1 GEMINI_API_KEY missing (env and .env both empty)');
    failures.push('P1: GEMINI_API_KEY missing');
  }

  // P2 — venv python.
  const py = resolveBrainPython(REPO_ROOT);
  try {
    fs.accessSync(py, fs.constants.X_OK);
    results.P2_venv = true;
    log(`  [✓] P2 brain venv python (${py})`);
  } catch (_) {
    log(`  [✗] P2 brain venv python missing or not executable: ${py}`);
    failures.push('P2: brain venv python missing');
  }

  // P3 — `python3 -m src --help` exits 0 (no LLM call, no body call).
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
      log('  [✓] P3 python -m src --help (exit 0, contains "goal")');
    } else {
      const tail = (helpRes.stderr || helpRes.stdout || '').slice(0, 500);
      log(`  [✗] P3 python -m src --help failed (status=${helpRes.status}): ${tail}`);
      failures.push(`P3: python -m src --help failed (status=${helpRes.status})`);
    }
  } else {
    log('  [✗] P3 skipped (P2 failed)');
    failures.push('P3: skipped (P2 failed)');
  }

  // P4 — results directory writable.
  try {
    await fsp.mkdir(RESULTS_DIR, { recursive: true });
    const probe = path.join(RESULTS_DIR, '.write-probe');
    await fsp.writeFile(probe, '');
    await fsp.unlink(probe);
    results.P4_resultsDir = true;
    log(`  [✓] P4 results dir writable (${RESULTS_DIR})`);
  } catch (err) {
    log(`  [✗] P4 results dir not writable: ${err.message}`);
    failures.push(`P4: results dir not writable: ${err.message}`);
  }

  // P5 — PID-file orphan check (may be tolerated via --force-kill, handled later).
  // We still report it here; the actual force-kill happens in main().
  try {
    const existing = await lifecycle.readPidFile(PID_FILE);
    if (!existing) {
      results.P5_pidOrphans = true;
      log('  [✓] P5 no PID file present');
    } else {
      const mcAlive = existing.mc ? lifecycle.isAlive(existing.mc) : false;
      const bodyAlive = existing.body ? lifecycle.isAlive(existing.body) : false;
      if (!mcAlive && !bodyAlive) {
        results.P5_pidOrphans = true;
        log('  [✓] P5 stale PID file only (no live processes)');
      } else if (config.forceKill) {
        results.P5_pidOrphans = true;
        log(`  [✓] P5 live PIDs detected (mc=${existing.mc}, body=${existing.body}) — will be killed by --force-kill`);
      } else {
        log(`  [✗] P5 live orphaned PIDs (mc=${existing.mc}, body=${existing.body}); rerun with --force-kill`);
        failures.push('P5: live orphaned PIDs (use --force-kill)');
      }
    }
  } catch (err) {
    log(`  [✗] P5 PID check error: ${err.message}`);
    failures.push(`P5: ${err.message}`);
  }

  const ok = failures.length === 0;
  return { ok, results, failures };
}

/**
 * Tap a child stdout/stderr stream into a rolling FIFO buffer of N lines.
 * Does NOT consume the stream destructively in a way that prevents other
 * readers — readline only listens, doesn't unpipe.
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
      '\n[brain-smoke] additional behavior: this entrypoint runs the Phase 3\n'
      + '              brain live-smoke (real Gemini call). Costs ~$0.005/run.\n'
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
    log('dry run: preflight passed and modules loaded; not spawning MC/body.');
    process.exit(0);
  }

  // --- Lifecycle setup ---------------------------------------------------
  const state = { mcProc: null, bodyProc: null, pidFile: PID_FILE, cleaned: false };
  lifecycle.registerSignalHandlers(state);

  // PID-file orphan recovery (mirrors run.js).
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

    // Tap body stdout into a rolling buffer for the artifact (post-waitForLog).
    // We start tapping immediately; waitForLog spins up its own reader on the
    // stdout stream too, so both readers coexist on the same Readable.
    bodyLogBuffer = tapRollingBuffer(bodyProc.stdout, BODY_LOG_BUFFER_SIZE, 'body');

    const client = createClient({
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

    // --- Brain scenario ---------------------------------------------------
    const runId = Date.now().toString(36);
    log(`Running brain CLI smoke (runId=${runId}); cost ~2 Gemini calls.`);
    brainResult = await runBrainSmoke({
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
    // Build artifact BEFORE cleanup so we capture body log buffer state.
    const artifact = {
      schemaVersion: 1,
      timestamp: new Date().toISOString(),
      verdict,
      durationMs: Date.now() - t0,
      preflight: {
        geminiKeyPresent: pre.results.P1_geminiKey,
        venvOk: pre.results.P2_venv,
        helpExitCode: pre.results.P3_brainHelp ? 0 : null,
        resultsDirOk: pre.results.P4_resultsDir,
        pidOrphansOk: pre.results.P5_pidOrphans,
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
        chatStepData: brainResult.chatStepData,
      } : null,
      assertions: brainResult ? brainResult.assertions : null,
      bodyLogExcerpt: bodyLogBuffer.slice(-BODY_LOG_BUFFER_SIZE),
      failureReasons,
    };
    try {
      await writeArtifact(artifact);
      log(`Artifact written: ${ARTIFACT_PATH}`);
    } catch (err) {
      logErr(`failed to write artifact: ${err.message}`);
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
