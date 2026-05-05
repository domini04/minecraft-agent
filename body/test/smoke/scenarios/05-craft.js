// T6 — craft scenario
// Clears inventory, gives 4 oak_planks, crafts a crafting_table, and verifies result.
// prepareWorkArea is called first so the bot is in a known-safe air pocket
// rather than potentially inside terracotta or other terrain blocks.

const { assertEnvelope } = require('../assertions');
const { prepareWorkArea, SETTLE_MS } = require('./_helpers');

module.exports = {
  name: 'craft',

  async setup(ctx) {
    // Teleport the bot to a clean work area before issuing inventory commands.
    // This prevents the bot from being suffocated inside terrain on non-flat seeds.
    await prepareWorkArea(ctx.client, ctx.spawn);

    // Clear everything then give 4 oak_planks.
    await ctx.client.execute('chat', { message: '/clear @s' });
    await ctx.client.execute('chat', { message: '/give @s oak_planks 4' });

    // Wait for the give to resolve server-side.
    await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
  },

  async run(ctx) {
    const env = await ctx.client.execute('craft', { item: 'crafting_table', count: 1 });

    assertEnvelope(env, { tool: 'craft', success: true });

    if (env.data.crafted !== 1) {
      throw new Error(`craft: expected data.crafted === 1, got ${env.data.crafted}`);
    }
    if (env.data.item !== 'crafting_table') {
      throw new Error(`craft: expected data.item === "crafting_table", got "${env.data.item}"`);
    }
    if (!(env.data.final_count >= 1)) {
      throw new Error(`craft: expected data.final_count >= 1, got ${env.data.final_count}`);
    }

    return env;
  },

  async teardown(ctx) {
    // Best-effort clear crafting_table from inventory.
    try {
      await ctx.client.execute('chat', { message: '/clear @s crafting_table' });
    } catch (err) {
      console.warn(`[05-craft] teardown: failed to clear crafting_table: ${err.message}`);
    }
  },
};
