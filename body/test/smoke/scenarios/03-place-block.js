// T4 — place_block scenario
// Uses /setblock + /tp to carve a deterministic work area above spawn
// (biome-independent), then places dirt at the known-air target cell.
// T5 (mine) depends on the dirt block this scenario leaves behind.

const { assertEnvelope, assertInventoryDelta } = require('../assertions');
const { prepareWorkArea, SETTLE_MS } = require('./_helpers');

module.exports = {
  name: 'place_block',

  async setup(ctx) {
    // Give the bot dirt so it has something to place.
    await ctx.client.execute('chat', { message: '/give @s dirt 8' });
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

    // Prepare a deterministic work area: stone floor, adjacent air target, bot tp'd on top.
    // Stores coords on ctx so run() can reference them without recomputing.
    ctx._placeWorkspace = await prepareWorkArea(ctx.client, ctx.spawn);

    // Capture inventory after the give (and after the tp settle) for delta check.
    const statusEnv = await ctx.client.execute('get_bot_status', {});
    ctx._placeBeforeInv = statusEnv.data.inventory;
  },

  async run(ctx) {
    // The target is the guaranteed-air cell adjacent to the stone floor.
    const { target } = ctx._placeWorkspace;

    const env = await ctx.client.execute('place_block', {
      block: 'dirt',
      x: target.x,
      y: target.y,
      z: target.z,
    });

    assertEnvelope(env, { tool: 'place_block', success: true });

    if (env.data.placed !== true) {
      throw new Error(`place_block: expected data.placed === true, got ${env.data.placed}`);
    }
    if (env.data.block !== 'dirt') {
      throw new Error(`place_block: expected data.block === "dirt", got "${env.data.block}"`);
    }

    // Re-fetch inventory for delta check.
    const afterEnv = await ctx.client.execute('get_bot_status', {});
    assertInventoryDelta(ctx._placeBeforeInv, afterEnv.data.inventory, 'dirt', -1);

    return env;
  },

  async teardown(ctx) {
    // Best-effort mine the placed dirt so subsequent runs don't collide.
    // (T5 will normally do this, but teardown protects against T5 being skipped.)
    try {
      await ctx.client.execute('mine', { target: 'dirt', count: 1, max_distance: 16 });
    } catch (err) {
      console.warn(`[03-place-block] teardown: failed to mine dirt: ${err.message}`);
    }
  },
};
