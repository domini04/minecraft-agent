// Tool: craft(item, count, crafting_table_pos?)
// Crafts `count` of `item` using the bot's inventory. When a 3x3 recipe
// is needed, `crafting_table_pos` ({x, y, z}) must be provided; the bot
// navigates to the table and crafts using it.
// Phase 2 implementation.

const Vec3 = require('vec3');
const { goals } = require('mineflayer-pathfinder');
const { validateParams } = require('../utils/validate_params');

/**
 * Crafts `count` of `item`, optionally using a crafting table at `crafting_table_pos`.
 *
 * @param {{item: string, count: number, crafting_table_pos?: {x: number, y: number, z: number}}} params
 *   - item: Item name (e.g. 'stick'). Must exist in bot.registry.itemsByName.
 *   - count: Number of items to craft. Must be a positive integer.
 *   - crafting_table_pos: Optional {x, y, z} integers. Required for 3x3 recipes.
 * @param {import('mineflayer').Bot} bot - The Mineflayer bot instance injected by the dispatcher.
 * @returns {Promise<{crafted: number, item: string, final_count: number}>}
 * @throws {Error} With 'craft:' prefix for all failure modes.
 */
async function craft(params, bot) {
  // --- Param validation (JSON-Schema-driven) ---
  validateParams('craft', params || {});
  const { item, count, crafting_table_pos } = params;

  // 4. bot must not be null/undefined
  if (!bot) {
    throw new Error('craft: bot not connected');
  }

  // 5. pathfinder guard — only required when crafting_table_pos is provided
  if (crafting_table_pos !== undefined && !bot.pathfinder) {
    throw new Error('craft: pathfinder plugin not loaded');
  }

  // 6. registry must be available
  if (!bot.registry || !bot.registry.itemsByName) {
    throw new Error('craft: bot registry not available (bot not spawned?)');
  }

  // 7. item must resolve to a known item
  const itemEntry = bot.registry.itemsByName[item];
  if (!itemEntry) {
    throw new Error(`craft: unknown item name "${item}"`);
  }
  const itemId = itemEntry.id;

  // --- Navigate to crafting table if pos provided ---
  let tableBlock = null;
  if (crafting_table_pos !== undefined) {
    const pos = Vec3(crafting_table_pos.x, crafting_table_pos.y, crafting_table_pos.z);

    try {
      await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, 2));
    } catch (err) {
      throw new Error(`craft: navigation to table failed: ${err.message}`);
    }

    tableBlock = bot.blockAt(pos);
    if (!tableBlock || tableBlock.name !== 'crafting_table') {
      throw new Error(
        `craft: no crafting_table at position {${pos.x},${pos.y},${pos.z}} (found ${tableBlock ? tableBlock.name : 'null'})`
      );
    }
  }

  // --- Find a craftable recipe ---
  const recipes = bot.recipesFor(itemId, null, count, tableBlock);
  const recipe = recipes && recipes[0];

  if (!recipe) {
    // Discriminate failure mode using recipesAll (ignores inventory)
    const allInv = bot.recipesAll(itemId, null, null);       // 2x2 recipes that exist at all
    const allTable = bot.recipesAll(itemId, null, tableBlock || true); // table-or-inv recipes

    if ((!allInv || allInv.length === 0) && (!allTable || allTable.length === 0)) {
      throw new Error(`craft: no recipe known for "${item}"`);
    }
    if ((!allInv || allInv.length === 0) && !tableBlock) {
      // 3x3 recipe exists but no table pos was provided
      throw new Error(
        `craft: ${item} requires a crafting_table; pass crafting_table_pos or place a table first via place_block`
      );
    }
    // Recipe(s) exist in this context but inventory is short on materials
    throw new Error(`craft: insufficient materials for ${item} x${count}`);
  }

  // --- Perform the craft ---
  try {
    await bot.craft(recipe, count, tableBlock);
  } catch (err) {
    throw new Error(`craft: bot.craft failed: ${err.message}`);
  }

  // --- Compute final_count from post-craft inventory ---
  const items = bot.inventory ? bot.inventory.items() : [];
  const finalCount = items
    .filter((it) => it.name === item)
    .reduce((sum, it) => sum + it.count, 0);

  return { crafted: count, item, final_count: finalCount };
}

module.exports = craft;
