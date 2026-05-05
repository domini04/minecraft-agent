// Tool: place_block(block, x, y, z)
// Navigates to an adjacent position, looks at the target coordinate,
// and places the block from inventory.
// Phase 2 (L3 stretch goal) implementation.

const Vec3 = require('vec3');
const { goals } = require('mineflayer-pathfinder');
const { validateParams } = require('../utils/validate_params');

/**
 * Returns how many milliseconds to wait after bot.placeBlock resolves before
 * re-reading world state to verify the placement was not reverted by the server.
 *
 * Resolution order:
 *   1. PLACE_BLOCK_VERIFY_SETTLE_MS env var (explicit override for tuning in production)
 *   2. JEST_WORKER_ID present → 0 ms (avoid 200ms × N dead time in jest)
 *   3. Default 200 ms (tight budget for server revert packets on localhost)
 */
function getSettleMs() {
  if (process.env.PLACE_BLOCK_VERIFY_SETTLE_MS !== undefined) {
    return Number(process.env.PLACE_BLOCK_VERIFY_SETTLE_MS);
  }
  if (process.env.JEST_WORKER_ID !== undefined) return 0;
  return 200;
}

/**
 * Places `block` at world coordinates (x, y, z).
 * Float coords are accepted and rounded with Math.round to the nearest block.
 *
 * @param {{block: string, x: number, y: number, z: number}} params
 *   - block: Block/item name (e.g. 'dirt'). Must exist in bot.registry.itemsByName.
 *   - x: Target block X coordinate (finite number, rounded).
 *   - y: Target block Y coordinate (finite number, rounded).
 *   - z: Target block Z coordinate (finite number, rounded).
 * @param {import('mineflayer').Bot} bot - The Mineflayer bot instance injected by the dispatcher.
 * @returns {Promise<{placed: true, block: string, position: {x: number, y: number, z: number}}>}
 * @throws {Error} With 'place_block: ' prefix for all failure modes, including
 *   'place_block: placement reverted by server (no block at {x,y,z} after placeBlock)'
 *   when the server reverts the placement after bot.placeBlock resolves.
 */
async function place_block(params, bot) {
  // --- Param validation (JSON-Schema-driven; finite-numbers post-pass
  //     in validateParams keeps T9c/T9d behavior identical). ---
  validateParams('place_block', params || {});
  const { block, x, y, z } = params;

  // 3. bot must not be null/undefined
  if (!bot) {
    throw new Error('place_block: bot not connected');
  }

  // 4. pathfinder guard (always required — we always navigate)
  if (!bot.pathfinder) {
    throw new Error('place_block: pathfinder plugin not loaded');
  }

  // 5. registry guard
  if (!bot.registry || !bot.registry.itemsByName) {
    throw new Error('place_block: bot registry not available (bot not spawned?)');
  }

  // 6. block name must resolve in registry
  if (!bot.registry.itemsByName[block]) {
    throw new Error(`place_block: unknown block "${block}"`);
  }

  // --- Coordinate rounding (D3) ---
  const tx = Math.round(x);
  const ty = Math.round(y);
  const tz = Math.round(z);

  // --- World-state check: target must be air (D2 step 7) ---
  const targetPos = Vec3(tx, ty, tz);
  const targetBlock = bot.blockAt(targetPos);
  if (targetBlock && targetBlock.name !== 'air') {
    throw new Error(`place_block: target already occupied by ${targetBlock.name}`);
  }

  // --- Neighbor scan (D4): first solid neighbor wins ---
  const neighbors = [
    { ref: Vec3(tx - 1, ty, tz),     face: Vec3( 1,  0,  0) }, // west neighbor's east face
    { ref: Vec3(tx + 1, ty, tz),     face: Vec3(-1,  0,  0) }, // east neighbor's west face
    { ref: Vec3(tx,     ty - 1, tz), face: Vec3( 0,  1,  0) }, // block below's top face
    { ref: Vec3(tx,     ty + 1, tz), face: Vec3( 0, -1,  0) }, // block above's bottom face
    { ref: Vec3(tx,     ty,     tz - 1), face: Vec3( 0,  0,  1) }, // north neighbor's south face
    { ref: Vec3(tx,     ty,     tz + 1), face: Vec3( 0,  0, -1) }, // south neighbor's north face
  ];

  let referenceBlock = null;
  let faceVec = null;

  for (const { ref, face } of neighbors) {
    const candidate = bot.blockAt(ref);
    if (candidate && candidate.name !== 'air') {
      referenceBlock = candidate;
      faceVec = face;
      break;
    }
  }

  if (!referenceBlock) {
    throw new Error(`place_block: no solid neighbor at {${tx},${ty},${tz}} to place against`);
  }

  // --- Navigate to within reach (D5) ---
  try {
    await bot.pathfinder.goto(new goals.GoalNear(tx, ty, tz, 3));
  } catch (err) {
    throw new Error(`place_block: navigation failed: ${err.message}`);
  }

  // --- Equip block from inventory (D6) ---
  const item = bot.inventory.items().find(i => i.name === block);
  if (!item) {
    throw new Error(`place_block: ${block} not in inventory`);
  }

  try {
    await bot.equip(item, 'hand');
  } catch (err) {
    throw new Error(`place_block: equip failed: ${err.message}`);
  }

  // --- Place the block (D7) ---
  try {
    await bot.placeBlock(referenceBlock, faceVec);
  } catch (err) {
    throw new Error(`place_block: placeBlock failed: ${err.message}`);
  }

  // --- Post-placement verification (Sprint 9) ---
  // bot.placeBlock resolves on packet acknowledgement, not on confirmed world
  // mutation. Server revert packets (Block-Update) arrive 50–500ms later.
  // Wait briefly then re-read world state to verify the block is actually there.
  await new Promise(r => setTimeout(r, getSettleMs()));
  const verifyBlock = bot.blockAt(targetPos);
  if (!verifyBlock || verifyBlock.name === 'air') {
    throw new Error(
      `place_block: placement reverted by server (no block at {${tx},${ty},${tz}} after placeBlock)`
    );
  }

  // --- Return success (D7) ---
  return { placed: true, block, position: { x: tx, y: ty, z: tz } };
}

module.exports = place_block;
