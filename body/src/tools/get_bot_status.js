// Tool: get_bot_status()
// Returns health, hunger, position, inventory contents, and nearby entities.
// This is the LLM's primary way of "seeing" the world state.
// Strategy A: reads exclusively from the passed-in bot argument (no module-level singleton).

/**
 * @param {object} _params - Ignored; no required fields.
 * @param {object} bot - The Mineflayer bot instance injected by the dispatcher.
 * @returns {Promise<{health, food, position, inventory, nearby_entities}>}
 */
async function get_bot_status(_params, bot) {
  if (!bot) {
    throw new Error('get_bot_status: bot not connected');
  }
  if (!bot.entity) {
    throw new Error('get_bot_status: bot has no entity yet');
  }

  const pos = bot.entity.position;

  const inventory = bot.inventory
    ? bot.inventory.items().map((item) => ({
        name: item.name,
        count: item.count,
      }))
    : [];

  const nearby_entities = Object.values(bot.entities)
    .filter((e) => e !== bot.entity && e.position.distanceTo(bot.entity.position) < 16)
    .map((e) => ({
      name: e.username || e.displayName || e.name || 'unknown',
      type: e.type,
      distance: Math.round(e.position.distanceTo(bot.entity.position) * 10) / 10,
    }));

  return {
    health: bot.health,
    food: bot.food,
    position: {
      x: Math.round(pos.x * 10) / 10,
      y: Math.round(pos.y * 10) / 10,
      z: Math.round(pos.z * 10) / 10,
    },
    inventory,
    nearby_entities,
  };
}

module.exports = get_bot_status;
