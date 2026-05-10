// Tool: mine(target, count, max_distance?)
// Finds the nearest block of the given type, navigates to it, mines it,
// collects the drop, and repeats until count is met.
// Phase 2 implementation.

const { validateParams } = require('../utils/validate_params');

const DEFAULT_MAX_DISTANCE = 32;

// --- Tier-based block selection (Sprint 3l) ---
//
// score = TIER * TIER_OFFSET + euclidean_distance(bot, block)
// Lower score wins. TIER_OFFSET (1000) > max possible euclidean distance
// within the schema-enforced max_distance of 128 (128*sqrt(3) ≈ 221.7),
// so tier order strictly dominates distance.
const TIER_LATERAL_OR_ABOVE = 0;
const TIER_BELOW_NOT_SUPPORT = 1;
const TIER_SUPPORT = 2;
const TIER_OFFSET = 1000;
const POOL_SIZE = 64;

/**
 * Classify a candidate block position relative to the bot's floored position.
 *
 * - TIER_SUPPORT (2): the block directly under the bot's feet.
 * - TIER_BELOW_NOT_SUPPORT (1): any block strictly below the bot's feet block,
 *   but not the support block itself.
 * - TIER_LATERAL_OR_ABOVE (0): blocks at the same y as the bot's feet block,
 *   or above.
 *
 * Note: the support check runs FIRST so it takes precedence over the more
 * generic below-feet test (a support block is a special case of below).
 *
 * @param {{x:number,y:number,z:number}} blockPos integer-aligned candidate block.
 * @param {{x:number,y:number,z:number}} botFloor floored bot position.
 * @returns {number} one of TIER_LATERAL_OR_ABOVE / TIER_BELOW_NOT_SUPPORT / TIER_SUPPORT.
 */
function classifyBlock(blockPos, botFloor) {
  const isSupport =
    blockPos.x === botFloor.x &&
    blockPos.y === botFloor.y - 1 &&
    blockPos.z === botFloor.z;
  if (isSupport) return TIER_SUPPORT;
  if (blockPos.y < botFloor.y) return TIER_BELOW_NOT_SUPPORT;
  return TIER_LATERAL_OR_ABOVE;
}

/**
 * Score a candidate block: tier * TIER_OFFSET + euclidean distance from
 * bot floor. Lower is better.
 *
 * @param {{x:number,y:number,z:number}} blockPos
 * @param {{x:number,y:number,z:number}} botFloor
 * @returns {number}
 */
function scoreCandidate(blockPos, botFloor) {
  const tier = classifyBlock(blockPos, botFloor);
  // Distance is measured from the floored bot position so test inputs are
  // fully reproducible from integer coordinates.
  const dx = blockPos.x - botFloor.x;
  const dy = blockPos.y - botFloor.y;
  const dz = blockPos.z - botFloor.z;
  const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
  return tier * TIER_OFFSET + dist;
}

/**
 * Pick the best mining target by tier preference + distance.
 * Returns the lowest-score Vec3 from up to POOL_SIZE candidates returned by
 * bot.findBlocks, or null if no candidates exist.
 *
 * @param {import('mineflayer').Bot} bot
 * @param {number} blockId  numeric block id from bot.registry
 * @param {number} maxDistance  search radius in blocks
 * @returns {object|null}  Vec3 (or Vec3-like {x,y,z}) of selected block, or null.
 */
function selectMineTarget(bot, blockId, maxDistance) {
  const candidates = bot.findBlocks({
    matching: [blockId],
    maxDistance,
    count: POOL_SIZE,
  });
  if (!candidates || candidates.length === 0) return null;

  // Spec note (Sprint 3l): we use bot.entity.position.floored() directly
  // (no -0.5 offset). The locked support predicate uses `botFloor.y - 1`
  // and that combination yields the correct support coordinates for the
  // common stationary feet-at-y=N+1.0 case. See notes.md ("Spec
  // Deviations") for the float-drift edge case deferred to follow-up.
  const botFloor = bot.entity.position.floored();

  let best = null;
  let bestScore = Infinity;
  for (const pos of candidates) {
    const s = scoreCandidate(pos, botFloor);
    // Strict < means the first candidate at the minimum score wins,
    // mirroring bot.findBlocks' distance-sorted return order. This
    // preserves the legacy bot.findBlock ordering for the lateral case.
    if (s < bestScore) {
      bestScore = s;
      best = pos;
    }
  }
  return best;
}

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
  // --- Param validation (JSON-Schema-driven) ---
  validateParams('mine', params || {});
  const { target, count, max_distance } = params;

  // JS-side default for max_distance — schemas describe shape, not behavior
  // (option 1 from sprint plan). Schema range [1,128] is enforced by ajv.
  const maxDistance =
    max_distance === undefined ? DEFAULT_MAX_DISTANCE : max_distance;

  // --- Bot/plugin guards ---
  if (!bot) {
    throw new Error('mine: bot not connected');
  }

  if (!bot.collectBlock) {
    throw new Error('mine: collectblock plugin not loaded');
  }

  // NOTE: this guard predates Sprint 3l. The new path uses bot.findBlocks
  // (plural) + bot.blockAt internally; we intentionally leave the
  // bot.findBlock guard untouched because mineflayer's Bot exposes all
  // three together — the existing guard remains a sufficient liveness
  // signal, and removing it would break the existing T9b test.
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
    const targetPos = selectMineTarget(bot, blockId, maxDistance);
    if (!targetPos) {
      throw new Error(
        `mine: no ${target} within ${maxDistance} blocks (collected ${i} of ${count})`
      );
    }
    const block = bot.blockAt(targetPos);
    if (!block) {
      // Block disappeared between findBlocks and blockAt (chunk unload race);
      // surface as the same not-found error so retries / brain see consistent shape.
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
module.exports.selectMineTarget = selectMineTarget;
module.exports.classifyBlock = classifyBlock;
module.exports.scoreCandidate = scoreCandidate;
module.exports.TIER_LATERAL_OR_ABOVE = TIER_LATERAL_OR_ABOVE;
module.exports.TIER_BELOW_NOT_SUPPORT = TIER_BELOW_NOT_SUPPORT;
module.exports.TIER_SUPPORT = TIER_SUPPORT;
module.exports.TIER_OFFSET = TIER_OFFSET;
module.exports.POOL_SIZE = POOL_SIZE;
