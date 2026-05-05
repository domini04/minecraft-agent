// Tool: navigate(x, y, z)
// Pathfinds and walks the bot to the given world coordinates.
// Phase 2 implementation.

const { goals } = require('mineflayer-pathfinder');
const { validateParams } = require('../utils/validate_params');

// Read once at module load — not per-call — because the value is env-configured
// and doesn't need to react to runtime changes.
const DEFAULT_THINK_TIMEOUT_MS = 20000;
function readEnvTimeout() {
  const raw = process.env.NAVIGATE_THINK_TIMEOUT_MS;
  if (raw === undefined) return DEFAULT_THINK_TIMEOUT_MS;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_THINK_TIMEOUT_MS;
}
const NAVIGATE_THINK_TIMEOUT_MS = readEnvTimeout();

/**
 * Pathfinds the bot to within 1 block of the integer block (x, y, z).
 * Uses GoalNear(tx, ty, tz, 1) instead of GoalBlock so that A* can succeed
 * even when the exact target tile is obstructed or difficult terrain, and
 * raises pathfinder.thinkTimeout to NAVIGATE_THINK_TIMEOUT_MS (default 20000 ms,
 * env-overridable via NAVIGATE_THINK_TIMEOUT_MS) around the goto call, restoring
 * the prior value afterwards so other tools (e.g. place_block) are unaffected.
 *
 * Float coords are accepted and rounded with Math.round to the nearest block.
 * Note: Math.round(20.5) === 21 (half rounds up for positives),
 *       Math.round(-20.5) === -20 (half rounds toward zero for negatives).
 *
 * @param {{x: number, y: number, z: number}} params - Target block coordinates.
 * @param {import('mineflayer').Bot} bot - The Mineflayer bot instance injected by the dispatcher.
 * @returns {Promise<{reached: true, position: {x: number, y: number, z: number}}>}
 */
async function navigate(params, bot) {
  validateParams('navigate', params || {});
  const { x, y, z } = params;

  if (!bot) {
    throw new Error('navigate: bot not connected');
  }
  if (!bot.pathfinder) {
    throw new Error('navigate: pathfinder plugin not loaded');
  }

  const tx = Math.round(x);
  const ty = Math.round(y);
  const tz = Math.round(z);
  const goal = new goals.GoalNear(tx, ty, tz, 1);

  const prevTimeout = bot.pathfinder.thinkTimeout;
  bot.pathfinder.thinkTimeout = NAVIGATE_THINK_TIMEOUT_MS;
  try {
    await bot.pathfinder.goto(goal);
  } catch (err) {
    throw new Error(`navigate: pathfinding failed: ${err.message}`);
  } finally {
    bot.pathfinder.thinkTimeout = prevTimeout;
  }

  const p = bot.entity.position;
  return {
    reached: true,
    position: {
      x: Math.round(p.x),
      y: Math.round(p.y),
      z: Math.round(p.z),
    },
  };
}

module.exports = navigate;
