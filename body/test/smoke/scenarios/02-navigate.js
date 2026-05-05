// T3 — navigate scenario
// Navigates to a point 3 blocks away from spawn and verifies arrival.

const { assertEnvelope, assertPositionNear } = require('../assertions');

module.exports = {
  name: 'navigate',

  async setup(ctx) {
    // Capture pre-position
    const statusEnv = await ctx.client.execute('get_bot_status', {});
    ctx._navigatePrePos = statusEnv.data.position;
  },

  async run(ctx) {
    const spawn = ctx.spawn;
    const target = {
      x: Math.floor(spawn.x) + 3,
      y: Math.floor(spawn.y),
      z: Math.floor(spawn.z) + 3,
    };

    const env = await ctx.client.execute('navigate', target);

    assertEnvelope(env, { tool: 'navigate', success: true });

    if (env.data.reached !== true) {
      throw new Error(`navigate: expected data.reached === true, got ${env.data.reached}`);
    }

    // Tolerance is 2.5 to accommodate Sprint 11's GoalNear(x,y,z,1) semantics:
    // the bot stops within 1 block of the goal, AND its feet land at y+1 because
    // it must stand on top of a solid block. Worst-case Euclidean distance is
    // √(1² + 2² + 1²) = √6 ≈ 2.45 (range=1 in x/z plus y+1 standing offset).
    // 2.5 covers the GoalNear corner case observed in run-6 (2.24 blocks).
    assertPositionNear(env.data.position, target, 2.5);

    return env;
  },

  async teardown(ctx) {
    // Best-effort return to anchor
    try {
      await ctx.client.execute('navigate', ctx.spawn);
    } catch (err) {
      console.warn(`[02-navigate] teardown: failed to return to spawn: ${err.message}`);
    }
  },
};
