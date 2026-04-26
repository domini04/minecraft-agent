// Tool: navigate(x, y, z)
// Pathfinds and walks the bot to the given world coordinates.
// Phase 2 implementation.

const { goals } = require('mineflayer-pathfinder');

/**
 * Pathfinds the bot to the integer block (x, y, z).
 * Float coords are accepted and rounded with Math.round to the nearest block.
 * Note: Math.round(20.5) === 21 (half rounds up for positives),
 *       Math.round(-20.5) === -20 (half rounds toward zero for negatives).
 *
 * @param {{x: number, y: number, z: number}} params - Target block coordinates.
 * @param {import('mineflayer').Bot} bot - The Mineflayer bot instance injected by the dispatcher.
 * @returns {Promise<{reached: true, position: {x: number, y: number, z: number}}>}
 */
async function navigate(params, bot) {
  const { x, y, z } = params || {};

  if (![x, y, z].every(Number.isFinite)) {
    throw new Error('navigate: x, y, z must be finite numbers');
  }
  if (!bot) {
    throw new Error('navigate: bot not connected');
  }
  if (!bot.pathfinder) {
    throw new Error('navigate: pathfinder plugin not loaded');
  }

  const tx = Math.round(x);
  const ty = Math.round(y);
  const tz = Math.round(z);
  const goal = new goals.GoalBlock(tx, ty, tz);

  try {
    await bot.pathfinder.goto(goal);
  } catch (err) {
    throw new Error(`navigate: pathfinding failed: ${err.message}`);
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
