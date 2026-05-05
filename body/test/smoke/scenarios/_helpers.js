// Shared helpers for world-mutating smoke scenarios (03-place-block, 04-mine, 05-craft).
// Not a scenario itself — index.js does not require() this file.

const SETTLE_MS = 1000;

/**
 * Computes the three work-area coordinates relative to the bot's spawn point.
 * Pure function — no side effects, no server commands.
 *
 * Layout (all at floorY = Math.floor(spawn.y) + 10):
 *   floor       (floorX,     floorY,     floorZ)     – stone block bot stands on
 *   target      (floorX + 1, floorY,     floorZ)     – air cell for place_block target
 *   standing    (floorX,     floorY + 1, floorZ)     – where the bot is tp'd (feet on floor)
 *
 * The +10 in y guarantees the work area is above terrain even on mesa/badlands seeds
 * (overworld build height is 320; spawn y ~63–70 + 10 = well within loaded air column).
 *
 * @param {{ x: number, y: number, z: number }} spawn
 * @returns {{ floor: {x,y,z}, target: {x,y,z}, standing: {x,y,z} }}
 */
function computeWorkAreaCoords(spawn) {
  const floorX = Math.floor(spawn.x) + 10;
  const floorY = Math.floor(spawn.y) + 10;
  const floorZ = Math.floor(spawn.z) + 10;

  return {
    floor:    { x: floorX,     y: floorY,     z: floorZ },
    target:   { x: floorX + 1, y: floorY,     z: floorZ },
    standing: { x: floorX,     y: floorY + 1, z: floorZ },
  };
}

/**
 * Prepares a deterministic work area in the world by:
 *   1. Setting a stone floor block  (/setblock floor stone)
 *   2. Clearing the place_block target cell  (/setblock target air)
 *   3. Clearing the bot-body cell  (/setblock standing air)
 *   4. Teleporting the bot onto the floor  (/tp @s standing)
 *   5. Sleeping SETTLE_MS to let chunk updates reach the bot's world view.
 *
 * Idempotent: calling it multiple times rewrites the same blocks, which is safe
 * UNLESS the placed dirt from T03 should be preserved (T04 must use computeWorkAreaCoords
 * + a bare /tp instead, to avoid overwriting the dirt with air).
 *
 * @param {{ execute: Function }} client  – smoke-test HTTP client
 * @param {{ x: number, y: number, z: number }} spawn
 * @returns {Promise<{ floor: {x,y,z}, target: {x,y,z}, standing: {x,y,z} }>}
 */
async function prepareWorkArea(client, spawn) {
  const coords = computeWorkAreaCoords(spawn);
  const { floor, target, standing } = coords;

  // Place a stone platform for the bot to stand on.
  await client.execute('chat', {
    message: `/setblock ${floor.x} ${floor.y} ${floor.z} minecraft:stone`,
  });

  // Guarantee the target cell (where place_block will place dirt) is air.
  await client.execute('chat', {
    message: `/setblock ${target.x} ${target.y} ${target.z} minecraft:air`,
  });

  // Guarantee the bot's body cell is clear so the tp doesn't suffocate it.
  await client.execute('chat', {
    message: `/setblock ${standing.x} ${standing.y} ${standing.z} minecraft:air`,
  });

  // Teleport the bot to the standing position (feet on the stone floor).
  await client.execute('chat', {
    message: `/tp @s ${standing.x} ${standing.y} ${standing.z}`,
  });

  // Wait for chunk updates to propagate to the bot's client-side world view.
  await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

  return coords;
}

module.exports = { computeWorkAreaCoords, prepareWorkArea, SETTLE_MS };
