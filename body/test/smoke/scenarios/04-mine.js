// T5 — mine scenario
// Depends on T4 having placed a dirt block at (spawn+10, spawn.y, spawn+10).
// Mines it and verifies inventory delta.

const { assertEnvelope, assertInventoryDelta } = require('../assertions');

module.exports = {
  name: 'mine',

  async setup(ctx) {
    // Capture inventory before mining
    const statusEnv = await ctx.client.execute('get_bot_status', {});
    ctx._mineBeforeInv = statusEnv.data.inventory;
  },

  async run(ctx) {
    const env = await ctx.client.execute('mine', {
      target: 'dirt',
      count: 1,
      max_distance: 16,
    });

    assertEnvelope(env, { tool: 'mine', success: true });

    if (env.data.items_collected !== 1) {
      throw new Error(`mine: expected items_collected === 1, got ${env.data.items_collected}`);
    }
    if (env.data.item_type !== 'dirt') {
      throw new Error(`mine: expected item_type === "dirt", got "${env.data.item_type}"`);
    }

    // Re-fetch inventory for delta check
    const afterEnv = await ctx.client.execute('get_bot_status', {});
    assertInventoryDelta(ctx._mineBeforeInv, afterEnv.data.inventory, 'dirt', +1);

    return env;
  },

  async teardown(ctx) {
    // Best-effort clear dirt from inventory
    try {
      await ctx.client.execute('chat', { message: '/clear @s dirt' });
    } catch (err) {
      console.warn(`[04-mine] teardown: failed to clear dirt: ${err.message}`);
    }
  },
};
