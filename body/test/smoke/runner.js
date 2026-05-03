// Scenario runner for the smoke test harness.
// Hand-rolled runner (not jest); iterates scenarios, captures results, and reports.

const fs = require('node:fs/promises');
const path = require('node:path');
const { AssertionError } = require('./assertions');

/**
 * Wraps a promise in a timeout.
 * @param {Promise} promise
 * @param {number} ms
 * @returns {Promise}
 */
function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`Scenario timed out after ${ms}ms`)),
      ms
    );
    promise.then(
      (val) => { clearTimeout(timer); resolve(val); },
      (err) => { clearTimeout(timer); reject(err); }
    );
  });
}

/**
 * Runs all scenarios in order.
 *
 * ctx = { client, config, spawn: {x,y,z}, runId }
 *
 * @param {Array<object>} scenarios
 * @param {object} ctx
 * @returns {Promise<{ allPassed: boolean, results: Array }>}
 */
async function runAll(scenarios, ctx) {
  const results = [];

  for (const scenario of scenarios) {
    const start = Date.now();
    let status = 'PASS';
    let error = null;
    let data = null;

    try {
      // 1. setup (optional)
      if (typeof scenario.setup === 'function') {
        await scenario.setup(ctx);
      }

      // 2. run (required), wrapped in timeout
      const result = await withTimeout(
        scenario.run(ctx),
        ctx.config ? ctx.config.scenarioTimeoutMs : 60000
      );
      data = result;

      // 3. assert (optional split)
      if (typeof scenario.assert === 'function') {
        await scenario.assert(result, ctx);
      }
    } catch (err) {
      status = 'FAIL';
      error = err;
      console.error(`[runner] FAIL ${scenario.name}: ${err.message}`);
      if (!(err instanceof AssertionError)) {
        console.error(err.stack);
      }
    } finally {
      // 4. teardown (best-effort, errors logged but don't fail)
      if (typeof scenario.teardown === 'function') {
        try {
          await scenario.teardown(ctx);
        } catch (tdErr) {
          console.warn(`[runner] teardown warning for ${scenario.name}: ${tdErr.message}`);
        }
      }
    }

    const durationMs = Date.now() - start;
    results.push({
      name: scenario.name,
      status,
      durationMs,
      ...(error ? { error: error.message } : {}),
      ...(data != null ? { data } : {}),
    });

    console.log(`[runner] ${status.padEnd(4)} ${scenario.name} (${durationMs}ms)`);
  }

  const allPassed = results.every((r) => r.status === 'PASS');
  return { allPassed, results };
}

/**
 * Prints a simple ASCII table to stream.
 *
 * @param {Array<{name, status, durationMs, error?}>} results
 * @param {NodeJS.WritableStream} [stream=process.stdout]
 */
function printTable(results, stream = process.stdout) {
  const NAME_W  = Math.max(20, ...results.map((r) => r.name.length));
  const SEP = `+${'-'.repeat(NAME_W + 2)}+--------+----------+${'-'.repeat(40)}+`;

  stream.write(`\n${SEP}\n`);
  stream.write(`| ${'Scenario'.padEnd(NAME_W)} | Status | Duration | Note${' '.repeat(35)}|\n`);
  stream.write(`${SEP}\n`);

  for (const r of results) {
    const note = (r.error || '').slice(0, 38).padEnd(38);
    stream.write(
      `| ${r.name.padEnd(NAME_W)} | ${r.status.padEnd(6)} | ${String(r.durationMs).padStart(7)}ms | ${note} |\n`
    );
  }

  stream.write(`${SEP}\n`);

  const passed = results.filter((r) => r.status === 'PASS').length;
  const failed = results.filter((r) => r.status === 'FAIL').length;
  stream.write(`\nResult: ${passed}/${results.length} passed, ${failed} failed\n`);
}

/**
 * Ensures parent dir exists, then writes pretty-printed JSON.
 *
 * @param {Array} results
 * @param {string} outPath
 */
async function writeJson(results, outPath) {
  await fs.mkdir(path.dirname(outPath), { recursive: true });
  await fs.writeFile(outPath, JSON.stringify(results, null, 2), 'utf8');
}

module.exports = { runAll, printTable, writeJson };
