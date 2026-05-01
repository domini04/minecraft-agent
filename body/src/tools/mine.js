// Tool: mine(target, count, max_distance?)
// Finds the nearest block of the given type, navigates to it, mines it,
// collects the drop, and repeats until count is met.
// Phase 2 implementation.

const DEFAULT_MAX_DISTANCE = 32;
const MAX_DISTANCE_CAP = 128;

/**
 * Mines `count` blocks of `target` type within `max_distance` blocks of the bot.
 * Uses mineflayer-collectblock to navigate, mine, and collect each block.
 *
 * @param {{target: string, count: number, max_distance?: number}} params
 *   - target: Block name (e.g. 'oak_log'). Must exist in bot.registry.blocksByName.
 *   - count: Number of blocks to mine. Must be a positive integer.
 *   - max_distance: Search radius in blocks. Default 32, max 128.
 * @param {import('mineflayer').Bot} bot - The Mineflayer bot instance injected by the dispatcher.
 * @returns {Promise<{items_collected: number, item_type: string, last_position: {x: number, y: number, z: number}}>}
 * @throws {Error} With 'mine:' prefix for all failure modes (param validation, bot state, block not found, collect failure).
 */
async function mine(params, bot) {
  // --- Param validation ---
  const { target, count, max_distance } = params || {};

  if (typeof target !== 'string' || target.trim() === '') {
    throw new Error('mine: target must be a non-empty string');
  }

  if (!Number.isInteger(count) || count < 1) {
    throw new Error('mine: count must be a positive integer');
  }

  const maxDistance =
    max_distance === undefined ? DEFAULT_MAX_DISTANCE : max_distance;

  if (max_distance !== undefined) {
    if (!Number.isInteger(max_distance) || max_distance < 1 || max_distance > MAX_DISTANCE_CAP) {
      throw new Error('mine: max_distance must be an integer between 1 and 128');
    }
  }

  // --- Bot/plugin guards ---
  if (!bot) {
    throw new Error('mine: bot not connected');
  }

  if (!bot.collectBlock) {
    throw new Error('mine: collectblock plugin not loaded');
  }

  if (!bot.findBlock) {
    throw new Error('mine: findBlock not available (bot not spawned?)');
  }

  if (!bot.registry || !bot.registry.blocksByName) {
    throw new Error('mine: bot registry not available (bot not spawned?)');
  }

  // --- Resolve block ID ---
  const blockEntry = bot.registry.blocksByName[target];
  if (!blockEntry) {
    throw new Error(`mine: unknown block name "${target}" (no entry in bot.registry.blocksByName)`);
  }
  const blockId = blockEntry.id;

  // --- Mining loop ---
  let collected = 0;
  let last_position = null;

  for (let i = 0; i < count; i++) {
    const block = bot.findBlock({ matching: [blockId], maxDistance });

    if (!block) {
      throw new Error(
        `mine: no ${target} within ${maxDistance} blocks (collected ${i} of ${count})`
      );
    }

    try {
      await bot.collectBlock.collect(block);
    } catch (err) {
      throw new Error(`mine: collect failed: ${err.message}`);
    }

    collected = i + 1;

    const p = bot.entity.position;
    last_position = {
      x: Math.round(p.x),
      y: Math.round(p.y),
      z: Math.round(p.z),
    };
  }

  return {
    items_collected: collected,
    item_type: target,
    last_position,
  };
}

module.exports = mine;
