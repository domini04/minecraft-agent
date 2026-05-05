// T5 — mine scenario
// Depends on T4 (place_block) having placed a dirt block at the work-area target.
// Bot is naturally at the work area after T4's place_block + Sprint 9 verify, so
// we DO NOT issue a /tp here — empirically /tp can trigger chunk-state churn that
// makes findBlock miss the freshly-placed dirt. We rely on the bot's natural
// post-place position and a generous max_distance for findBlock instead.

const { assertEnvelope, assertInventoryDelta } = require('../assertions');

module.exports = {
  name: 'mine',

  async setup(ctx) {
    // Capture inventory before mining. The bot is already at the work area from T4.
    // No /tp, no setblock — anything we do here risks evicting the dirt block from
    // the bot's local chunk cache.
    const statusEnv = await ctx.client.execute('get_bot_status', {});
    ctx._mineBeforeInv = statusEnv.data.inventory;
  },

  async run(ctx) {
    // max_distance: 16 — the placed dirt is 1 block laterally from the bot's standing
    // position. The work area sits at floor.y = spawn.y + 10 (a sky pocket above terrain),
    // so there is no natural dirt at this altitude to confuse with. We use a generous radius
    // to absorb any chunk-cache or position-rounding drift between place_block and mine.
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

    // Re-fetch inventory for delta check.
    const afterEnv = await ctx.client.execute('get_bot_status', {});
    assertInventoryDelta(ctx._mineBeforeInv, afterEnv.data.inventory, 'dirt', +1);

    return env;
  },

  async teardown(ctx) {
    // Best-effort clear dirt from inventory.
    try {
      await ctx.client.execute('chat', { message: '/clear @s dirt' });
    } catch (err) {
      console.warn(`[04-mine] teardown: failed to clear dirt: ${err.message}`);
    }
  },
};
