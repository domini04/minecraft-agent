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

    assertPositionNear(env.data.position, target, 1.5);

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
