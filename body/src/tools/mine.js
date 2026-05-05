// Tool: mine(target, count, max_distance?)
// Finds the nearest block of the given type, navigates to it, mines it,
// collects the drop, and repeats until count is met.
// Phase 2 implementation.

const DEFAULT_MAX_DISTANCE = 32;
const MAX_DISTANCE_CAP = 128;

/**
 * Returns how many milliseconds to wait after bot.collectBlock.collect resolves
 * before re-reading inventory to verify the item was actually picked up.
 *
 * Resolution order:
 *   1. MINE_VERIFY_SETTLE_MS env var (explicit override for tuning in production)
 *   2. JEST_WORKER_ID present → 0 ms (avoid 200ms × N dead time in jest)
 *   3. Default 200 ms (sufficient budget for pickup packet round-trip on localhost)
 */
function getSettleMs() {
  if (process.env.MINE_VERIFY_SETTLE_MS !== undefined) {
    return Number(process.env.MINE_VERIFY_SETTLE_MS);
  }
  if (process.env.JEST_WORKER_ID !== undefined) return 0;
  return 200;
}

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

  // Helper: count how many of `target` are currently in inventory.
  // NOTE: Assumes target block name === item name. This holds for the MVP block
  // list (dirt, oak_log, stone, cobblestone). Blocks whose drops differ from
  // their name (e.g. coal_ore → coal) are deferred to a future drop-table sprint.
  const countTarget = () =>
    bot.inventory.items()
      .filter(it => it.name === target)
      .reduce((sum, it) => sum + it.count, 0);

  // Capture inventory baseline before loop starts (D6).
  let baseline = countTarget();

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

    // --- Post-collect inventory verification (Sprint 10) ---
    // bot.collectBlock.collect resolves on dig completion, not confirmed pickup.
    // Wait briefly then verify inventory actually grew for this target item.
    await new Promise(r => setTimeout(r, getSettleMs()));
    const current = countTarget();
    if (current <= baseline) {
      throw new Error(
        `mine: collect resolved but inventory did not increase for "${target}" ` +
        `(collected ${i} of ${count} dug-and-resolved; possible pickup race)`
      );
    }
    baseline = current;

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
