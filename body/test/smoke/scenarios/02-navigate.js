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

    // Tolerance is 2.0 to accommodate pathfinder's GoalBlock(x,y,z) semantics:
    // the bot stands ON the goal block, so its feet are at y+1 relative to the
    // target coordinate. Combined with pathfinder's typical corner-cell finish,
    // the observed Euclidean distance from a successful navigate to the target
    // floor coordinate can reach √3 ≈ 1.73 (one block off in each axis). 2.0
    // keeps the assertion strict enough to catch real failures while permitting
    // the inherent y+1 standing offset.
    assertPositionNear(env.data.position, target, 2.0);

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
