// T2 — get_bot_status scenario
// Verifies the bot status data shape end-to-end.

const { assertEnvelope } = require('../assertions');

module.exports = {
  name: 'get_bot_status',

  async run(ctx) {
    const env = await ctx.client.execute('get_bot_status', {});

    assertEnvelope(env, { tool: 'get_bot_status', success: true });

    const { health, position, inventory, nearby_entities } = env.data;

    if (!Number.isFinite(health) || health <= 0) {
      throw new Error(`get_bot_status: expected health > 0, got ${health}`);
    }

    if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y) || !Number.isFinite(position.z)) {
      throw new Error(`get_bot_status: expected finite position {x,y,z}, got ${JSON.stringify(position)}`);
    }

    if (!Array.isArray(inventory)) {
      throw new Error(`get_bot_status: expected inventory to be an array, got ${typeof inventory}`);
    }

    if (!Array.isArray(nearby_entities)) {
      throw new Error(`get_bot_status: expected nearby_entities to be an array, got ${typeof nearby_entities}`);
    }

    return env;
  },
};
