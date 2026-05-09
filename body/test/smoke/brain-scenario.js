// brain-scenario.js — drive the Python brain CLI as a subprocess and assert.
//
// Sprint 3i live-smoke gate. Spawns `python3 -m src "<goal>" --verbose` from
// the brain/ directory, captures stdout/stderr, then runs the five gating
// assertions A1..A5 (plus informational A6) by parsing the CLI's frozen
// summary block (see brain/src/__main__.py:_format_summary).
//
// This module is purely transport + parsing; lifecycle (MC + body) is the
// caller's responsibility. No deps beyond Node stdlib.

const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

// Frozen behavior knobs.
// 180s ceiling: the planner LLM call observed ~7s/iter; the worst-case
// (MAX_ITERATIONS=10) round-trip is ~70-90s on Gemini 3.1 Flash Lite plus body
// roundtrips, so 180s leaves clear headroom for diagnosis without indefinite
// blocking. Expected happy-path runs are ~15-20s (2 LLM calls + 1 chat tool).
const BRAIN_TIMEOUT_MS = 180_000;      // hard ceiling on the child process.
const ITERATION_BUDGET = 4;            // A4 — expected=2, headroom of 2.
const ITERATION_CAP = 10;              // matches src.state.MAX_ITERATIONS.

/**
 * Parse the CLI summary block out of stdout.
 * The summary format (frozen in brain/src/__main__.py):
 *   Goal: <goal>
 *   Iterations: <n> (cap=10)
 *   Steps: <n>
 *     [<i>] <tool>           success=True   data=<...>
 *     [<i>] <tool>           success=False  error=<...>
 *   Result: <text>
 *
 * @param {string} stdout
 * @returns {{goalLine: string|null, iterationCount: number|null,
 *            stepsCount: number|null, stepLines: string[],
 *            resultLine: string|null, resultValue: string|null}}
 */
function parseSummary(stdout) {
  const lines = stdout.split('\n');

  let goalLine = null;
  let iterationCount = null;
  let stepsCount = null;
  let resultLine = null;
  let resultValue = null;
  const stepLines = [];

  // Iteration: literal /^Iterations: (\d+) \(cap=10\)$/
  const iterRe = /^Iterations: (\d+) \(cap=10\)$/;
  const stepsRe = /^Steps: (\d+)$/;
  const stepRe = /^\s*\[(\d+)\]\s+\S/;
  // Match the FIRST "Result: ..." (summary is printed before optional verbose).
  const resultRe = /^Result: (.*)$/;

  for (const line of lines) {
    if (goalLine === null && line.startsWith('Goal: ')) {
      goalLine = line;
      continue;
    }
    const itM = iterRe.exec(line);
    if (itM && iterationCount === null) {
      iterationCount = parseInt(itM[1], 10);
      continue;
    }
    const stM = stepsRe.exec(line);
    if (stM && stepsCount === null) {
      stepsCount = parseInt(stM[1], 10);
      continue;
    }
    if (stepRe.test(line)) {
      stepLines.push(line);
      continue;
    }
    const rM = resultRe.exec(line);
    if (rM && resultLine === null) {
      resultLine = line;
      resultValue = rM[1];
      // do NOT break — verbose dump may follow but the first match is the summary.
    }
  }

  return { goalLine, iterationCount, stepsCount, stepLines, resultLine, resultValue };
}

/**
 * Find the first chat step that succeeded; return its parsed data tail or null.
 * Step line format (frozen):
 *   "  [<idx>] chat            success=True   data=sent=True,message=<...>"
 *
 * @param {string[]} stepLines
 * @returns {{idx: number, dataTail: string, messageValue: string|null,
 *            sentTrue: boolean}|null}
 */
function findChatSuccess(stepLines) {
  // Tool name is space-padded to _TOOL_PAD=16; allow any whitespace.
  const re = /^\s*\[(\d+)\]\s+chat\s+success=True\s+(data=.+)$/;
  for (const line of stepLines) {
    const m = re.exec(line);
    if (m) {
      const idx = parseInt(m[1], 10);
      const dataTail = m[2]; // e.g. "data=sent=True,message=hello"
      const sentTrue = /\bsent=True\b/.test(dataTail);
      const msgRe = /\bmessage=([^,]+)$/;
      const msgM = msgRe.exec(dataTail);
      const messageValue = msgM ? msgM[1] : null;
      return { idx, dataTail, messageValue, sentTrue };
    }
  }
  return null;
}

/**
 * Check stderr for the CLI's hard-failure prefix (`error: `).
 * Soft warnings (WARNING:, dotenv noise, urllib3 deprecation) are tolerated.
 *
 * @param {string} stderr
 * @returns {boolean} true iff a hard "error:" line was found
 */
function hasHardErrorLine(stderr) {
  for (const line of stderr.split('\n')) {
    // Match the exact prefix used by __main__.py (line 225, 234).
    if (/^error: /.test(line)) return true;
  }
  return false;
}

/**
 * Build assertion verdicts from raw streams. Pure function — no I/O.
 *
 * @param {{exitCode: number|null, stdout: string, stderr: string}} run
 * @returns {{
 *   verdict: 'PASS'|'FAIL',
 *   reasons: string[],
 *   assertions: Record<string, 'PASS'|'FAIL'|'WARN'>,
 *   iterationCount: number|null,
 *   stepsCount: number|null,
 *   chatStepData: string|null,
 *   finalResultLine: string|null,
 * }}
 */
function assertSmoke(run) {
  const { exitCode, stdout, stderr } = run;
  const summary = parseSummary(stdout);
  const chat = findChatSuccess(summary.stepLines);

  const assertions = {
    A1_exit0: exitCode === 0 ? 'PASS' : 'FAIL',
    A2_resultLine: 'FAIL',
    A3_chatSuccess: 'FAIL',
    A4_iterationsBudget: 'FAIL',
    A5_noStderrErrors: hasHardErrorLine(stderr) ? 'FAIL' : 'PASS',
    A6_stepsCountMatches: 'WARN', // informational by default
  };
  const reasons = [];

  if (assertions.A1_exit0 === 'FAIL') {
    reasons.push(`A1: brain CLI exited with code ${exitCode} (expected 0)`);
  }

  // A2: Result line present and not the placeholder.
  const placeholder = '(no result -- cap exhausted or failure)';
  if (summary.resultValue && summary.resultValue.trim().length > 0
      && summary.resultValue !== placeholder) {
    assertions.A2_resultLine = 'PASS';
  } else if (summary.resultLine === null) {
    reasons.push('A2: no "Result:" line found in stdout');
  } else {
    reasons.push(`A2: Result line was empty or placeholder: ${JSON.stringify(summary.resultValue)}`);
  }

  // A3: at least one chat step success=True with sent=True and non-empty message.
  if (chat && chat.sentTrue && chat.messageValue
      && chat.messageValue.trim().length > 0) {
    assertions.A3_chatSuccess = 'PASS';
  } else if (!chat) {
    reasons.push('A3: no successful chat step found in step list');
  } else {
    reasons.push(`A3: chat step missing sent=True or non-empty message; data=${chat.dataTail}`);
  }

  // A4: iterations <= budget.
  if (summary.iterationCount === null) {
    reasons.push('A4: could not parse "Iterations:" line');
  } else if (summary.iterationCount <= ITERATION_BUDGET) {
    assertions.A4_iterationsBudget = 'PASS';
  } else {
    reasons.push(`A4: iteration_count=${summary.iterationCount} exceeded budget=${ITERATION_BUDGET}`);
  }

  if (assertions.A5_noStderrErrors === 'FAIL') {
    reasons.push('A5: stderr contained a hard "error:" line');
  }

  // A6 (informational): does Steps: <n> match number of [i] lines?
  if (summary.stepsCount !== null
      && summary.stepsCount === summary.stepLines.length) {
    assertions.A6_stepsCountMatches = 'PASS';
  }

  // Verdict: A1..A5 are gating.
  const gating = ['A1_exit0', 'A2_resultLine', 'A3_chatSuccess',
                  'A4_iterationsBudget', 'A5_noStderrErrors'];
  const allPass = gating.every((k) => assertions[k] === 'PASS');

  return {
    verdict: allPass ? 'PASS' : 'FAIL',
    reasons,
    assertions,
    iterationCount: summary.iterationCount,
    stepsCount: summary.stepsCount,
    chatStepData: chat ? chat.dataTail : null,
    finalResultLine: summary.resultLine,
  };
}

/**
 * Resolve the path to the brain venv's python3.
 * @param {string} repoRoot
 * @returns {string}
 */
function resolveBrainPython(repoRoot) {
  return path.join(repoRoot, 'brain', '.venv', 'bin', 'python3');
}

/**
 * Spawn `python3 -m src "<goal>" --verbose` from brain/ and capture output.
 * Returns the raw process result; assertion is left to the caller via
 * assertSmoke().
 *
 * @param {object} ctx
 * @param {object} ctx.config         smoke-harness config (botHost, botPort, ...)
 * @param {string} [ctx.goal]         override default goal
 * @param {object} [ctx.env]          extra env (merged over process.env)
 * @returns {Promise<{
 *   exitCode: number|null,
 *   stdout: string,
 *   stderr: string,
 *   durationMs: number,
 *   command: string,
 *   cwd: string,
 *   verdict: string,
 *   reasons: string[],
 *   assertions: object,
 *   iterationCount: number|null,
 *   stepsCount: number|null,
 *   chatStepData: string|null,
 *   finalResultLine: string|null,
 * }>}
 */
async function runBrainSmoke(ctx) {
  const { config } = ctx;
  const goal = ctx.goal || 'say hello in chat';
  const repoRoot = path.resolve(__dirname, '..', '..', '..');
  const brainCwd = path.join(repoRoot, 'brain');
  const py = resolveBrainPython(repoRoot);

  if (!fs.existsSync(py)) {
    throw new Error(`brain venv python not found at ${py}`);
  }

  const childEnv = {
    ...process.env,
    ...(ctx.env || {}),
    BOT_HOST: config.botHost,
    BOT_PORT: String(config.botPort),
    BOT_URL: `http://${config.botHost}:${config.botPort}`,
    // Force unbuffered Python stdout/stderr so we get streaming visibility
    // for debugging — the brain CLI itself only flushes on exit otherwise.
    PYTHONUNBUFFERED: '1',
  };

  const args = ['-m', 'src', goal, '--verbose'];
  const command = `${py} ${args.map((a) => (a.includes(' ') ? JSON.stringify(a) : a)).join(' ')}`;
  const start = Date.now();

  const child = spawn(py, args, {
    cwd: brainCwd,
    env: childEnv,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  const stdoutChunks = [];
  const stderrChunks = [];
  child.stdout.on('data', (c) => {
    stdoutChunks.push(c);
    process.stdout.write(`[brain] ${c.toString('utf8').replace(/\n$/, '').replace(/\n/g, '\n[brain] ')}\n`);
  });
  child.stderr.on('data', (c) => {
    stderrChunks.push(c);
    process.stderr.write(`[brain-err] ${c.toString('utf8').replace(/\n$/, '').replace(/\n/g, '\n[brain-err] ')}\n`);
  });

  let timedOut = false;
  const exitCode = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch (_) {}
      reject(new Error(`brain CLI timed out after ${BRAIN_TIMEOUT_MS}ms`));
    }, BRAIN_TIMEOUT_MS);

    child.on('exit', (code) => { clearTimeout(timer); resolve(code); });
    child.on('error', (err) => { clearTimeout(timer); reject(err); });
  }).catch((err) => {
    if (timedOut) return null;
    throw err;
  });

  const stdout = Buffer.concat(stdoutChunks).toString('utf8');
  const stderr = Buffer.concat(stderrChunks).toString('utf8');
  const durationMs = Date.now() - start;

  const verdict = assertSmoke({ exitCode, stdout, stderr });

  return {
    exitCode,
    stdout,
    stderr,
    durationMs,
    command,
    cwd: brainCwd,
    ...verdict,
  };
}

module.exports = {
  runBrainSmoke,
  assertSmoke,
  parseSummary,
  findChatSuccess,
  hasHardErrorLine,
  resolveBrainPython,
  ITERATION_BUDGET,
  ITERATION_CAP,
  BRAIN_TIMEOUT_MS,
};
