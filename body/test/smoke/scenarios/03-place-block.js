// T4 — place_block scenario
// Gives the bot 8 dirt, places one at (spawn+10, spawn.y, spawn+10),
// and verifies inventory delta.

const { assertEnvelope, assertInventoryDelta } = require('../assertions');

const SETTLE_MS = 1000;

module.exports = {
  name: 'place_block',

  async setup(ctx) {
    // Give the bot dirt so it has something to place
    await ctx.client.execute('chat', { message: '/give @s dirt 8' });

    // Wait for the give to resolve server-side
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

    // Capture inventory before placement
    const statusEnv = await ctx.client.execute('get_bot_status', {});
    ctx._placeBeforeInv = statusEnv.data.inventory;
  },

  async run(ctx) {
    const spawn = ctx.spawn;
    const target = {
      block: 'dirt',
      x: spawn.x + 10,
      y: spawn.y,
      z: spawn.z + 10,
    };

    const env = await ctx.client.execute('place_block', target);

    assertEnvelope(env, { tool: 'place_block', success: true });

    if (env.data.placed !== true) {
      throw new Error(`place_block: expected data.placed === true, got ${env.data.placed}`);
    }
    if (env.data.block !== 'dirt') {
      throw new Error(`place_block: expected data.block === "dirt", got "${env.data.block}"`);
    }

    // Re-fetch inventory for delta check
    const afterEnv = await ctx.client.execute('get_bot_status', {});
    assertInventoryDelta(ctx._placeBeforeInv, afterEnv.data.inventory, 'dirt', -1);

    return env;
  },

  async teardown(ctx) {
    // Best-effort mine the placed dirt so subsequent runs don't collide
    // (T5 will normally do this, but teardown protects against T5 being skipped)
    try {
      await ctx.client.execute('mine', { target: 'dirt', count: 1, max_distance: 16 });
    } catch (err) {
      console.warn(`[03-place-block] teardown: failed to mine dirt: ${err.message}`);
    }
  },
};
