// T5 — mine scenario
// Depends on T4 (place_block) having placed a dirt block at the work-area target.
// Uses the PURE coord helper (computeWorkAreaCoords) rather than prepareWorkArea so
// we do NOT re-setblock the target cell to air — that would destroy the dirt T4 left.
// Only a single /tp is issued to return the bot to the standing position.

const { assertEnvelope, assertInventoryDelta } = require('../assertions');
const { computeWorkAreaCoords, SETTLE_MS } = require('./_helpers');

module.exports = {
  name: 'mine',

  async setup(ctx) {
    // Recompute the same work-area coords T4 used — pure, no server commands.
    const { standing } = computeWorkAreaCoords(ctx.spawn);

    // Re-tp the bot to the standing position in case it drifted during T4's place_block.
    // We do NOT call prepareWorkArea here because that would /setblock the target to air,
    // destroying the dirt block that T4 placed and that we are about to mine.
    await ctx.client.execute('chat', {
      message: `/tp @s ${standing.x} ${standing.y} ${standing.z}`,
    });
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

    // Capture inventory before mining.
    const statusEnv = await ctx.client.execute('get_bot_status', {});
    ctx._mineBeforeInv = statusEnv.data.inventory;
  },

  async run(ctx) {
    // max_distance: 4 — the placed dirt is 1 block laterally from the bot's standing
    // position, so it will always be within 4. The tight radius prevents findBlock from
    // matching any natural dirt that may exist further away in the world.
    const env = await ctx.client.execute('mine', {
      target: 'dirt',
      count: 1,
      max_distance: 4,
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
