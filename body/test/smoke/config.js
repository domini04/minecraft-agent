// Smoke test harness configuration
// Resolves env-var configuration with documented defaults.

const path = require('node:path');
const os = require('node:os');

const DEFAULTS = {
  mcServerDir: path.join(os.homedir(), 'minecraft-server'),
  botHost: '127.0.0.1',
  botPort: 3000,
  mcHost: 'localhost',
  mcPort: 25565,
  mcUsername: 'agent',
  mcReadyTimeoutMs: 120000,
  botReadyTimeoutMs: 60000,
  scenarioTimeoutMs: 60000,
  keepWorld: false,
  forceKill: false,
  dryRun: false,
  help: false,
  down: false,
};

/**
 * Parses CLI flags from argv.
 * Recognised flags: --keep-world, --force-kill, --dry-run, --down, --help/-h
 *
 * @param {string[]} argv
 * @returns {{ keepWorld, forceKill, dryRun, down, help }}
 */
function parseArgs(argv) {
  const flags = {
    keepWorld: false,
    forceKill: false,
    dryRun: false,
    down: false,
    help: false,
  };
  for (const arg of argv) {
    switch (arg) {
      case '--keep-world': flags.keepWorld = true; break;
      case '--force-kill': flags.forceKill = true; break;
      case '--dry-run':    flags.dryRun = true;    break;
      case '--down':       flags.down = true;      break;
      case '--help':
      case '-h':           flags.help = true;      break;
    }
  }
  return flags;
}

/**
 * Writes usage text to stream (defaults stdout).
 * @param {NodeJS.WritableStream} stream
 */
function printHelp(stream = process.stdout) {
  stream.write(`
Usage: node test/smoke/run.js [options]
       node test/smoke/dev-up.js [options]

Smoke-test harness for the Minecraft Agent body server.
Starts a real MC server and body server, runs six tool scenarios, then tears down.

Options:
  --keep-world    Skip world reset (do not delete world/, world_nether/, world_the_end/).
  --force-kill    Kill any orphaned MC/body processes found in the PID file before starting.
  --dry-run       Load config and scenarios, print summary, exit 0. Do not spawn anything.
  --down          (dev-up.js only) Tear down running instances from the PID file.
  --help, -h      Print this help text and exit 0.

Environment variables:
  MC_SERVER_DIR              Path to MC server directory (default: ~/minecraft-server)
  BOT_HOST                   Body server bind host (default: 127.0.0.1)
  BOT_PORT                   Body server port (default: 3000)
  MC_HOST                    MC server host for bot connection (default: localhost)
  MC_PORT                    MC server port (default: 25565)
  MC_USERNAME                Bot username (default: agent)
  SMOKE_MC_READY_TIMEOUT_MS  How long to wait for MC server ready (default: 120000)
  SMOKE_BOT_READY_TIMEOUT_MS How long to wait for body server ready (default: 60000)
  SMOKE_SCENARIO_TIMEOUT_MS  Per-scenario timeout in ms (default: 60000)
  KEEP_WORLD                 Set to '1' or 'true' to skip world reset
`);
}

/**
 * Loads full configuration from env vars and CLI flags.
 * CLI flags override env vars; env vars override defaults.
 *
 * @param {string[]} argv
 * @returns {object}
 */
function loadConfig(argv = process.argv.slice(2)) {
  const flags = parseArgs(argv);

  const keepWorldEnv = process.env.KEEP_WORLD === '1' || process.env.KEEP_WORLD === 'true';

  return {
    mcServerDir:        process.env.MC_SERVER_DIR || DEFAULTS.mcServerDir,
    botHost:            process.env.BOT_HOST      || DEFAULTS.botHost,
    botPort:            parseInt(process.env.BOT_PORT, 10) || DEFAULTS.botPort,
    mcHost:             process.env.MC_HOST       || DEFAULTS.mcHost,
    mcPort:             parseInt(process.env.MC_PORT, 10) || DEFAULTS.mcPort,
    mcUsername:         process.env.MC_USERNAME   || DEFAULTS.mcUsername,
    mcReadyTimeoutMs:   parseInt(process.env.SMOKE_MC_READY_TIMEOUT_MS, 10)  || DEFAULTS.mcReadyTimeoutMs,
    botReadyTimeoutMs:  parseInt(process.env.SMOKE_BOT_READY_TIMEOUT_MS, 10) || DEFAULTS.botReadyTimeoutMs,
    scenarioTimeoutMs:  parseInt(process.env.SMOKE_SCENARIO_TIMEOUT_MS, 10)  || DEFAULTS.scenarioTimeoutMs,
    keepWorld:          keepWorldEnv || flags.keepWorld,
    forceKill:          flags.forceKill,
    dryRun:             flags.dryRun,
    help:               flags.help,
    down:               flags.down,
  };
}

module.exports = { loadConfig, parseArgs, printHelp, DEFAULTS };
