// World reset utilities.
// Deletes MC world directories and ensures the bot account is op'd.

const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');

const WORLD_DIRS = ['world', 'world_nether', 'world_the_end'];

/**
 * Defensive guard: refuse to operate on dangerous paths.
 * @param {string} mcServerDir
 */
function validateServerDir(mcServerDir) {
  if (!mcServerDir || mcServerDir === '/') {
    throw new Error('world-reset: mcServerDir must not be empty or root "/"');
  }

  const resolved = path.resolve(mcServerDir);

  if (resolved === '/') {
    throw new Error('world-reset: resolved mcServerDir must not be root "/"');
  }

  const home = os.homedir();
  if (!resolved.startsWith(home + path.sep) && resolved !== home) {
    throw new Error(
      `world-reset: mcServerDir "${resolved}" is not under home directory "${home}"`
    );
  }
}

/**
 * Deletes world/, world_nether/, world_the_end/ inside mcServerDir.
 * Idempotent — missing directories are silently ignored.
 *
 * @param {string} mcServerDir
 */
async function resetWorld(mcServerDir) {
  validateServerDir(mcServerDir);

  const resolved = path.resolve(mcServerDir);

  for (const dir of WORLD_DIRS) {
    const target = path.join(resolved, dir);
    try {
      await fs.rm(target, { recursive: true, force: true });
      console.log(`[world-reset] Removed ${target}`);
    } catch (err) {
      // force: true means missing dirs are fine; log unexpected errors
      if (err.code !== 'ENOENT') {
        console.warn(`[world-reset] Warning: failed to remove ${target}: ${err.message}`);
      }
    }
  }
}

/**
 * Computes the deterministic offline-mode UUID for a Minecraft username.
 * Uses MD5("OfflinePlayer:<name>") with version-3 and variant bits set per RFC 4122.
 *
 * @param {string} username
 * @returns {string} UUID string (e.g. "xxxxxxxx-xxxx-3xxx-yxxx-xxxxxxxxxxxx")
 */
function offlineUuidFor(username) {
  const hash = crypto.createHash('md5').update(`OfflinePlayer:${username}`).digest();

  // Set version 3: bits 12-15 of byte 6 = 0011
  hash[6] = (hash[6] & 0x0f) | 0x30;

  // Set variant: bits 6-7 of byte 8 = 10
  hash[8] = (hash[8] & 0x3f) | 0x80;

  const hex = hash.toString('hex');
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32),
  ].join('-');
}

/**
 * Ensures the given username is listed in ops.json with level 4.
 * Creates ops.json (as []) if absent.
 * Appends an entry only if no existing entry matches the username.
 *
 * @param {string} mcServerDir
 * @param {string} username
 */
async function ensureBotIsOp(mcServerDir, username) {
  validateServerDir(mcServerDir);

  const resolved = path.resolve(mcServerDir);
  const opsPath = path.join(resolved, 'ops.json');

  let ops = [];
  try {
    const raw = await fs.readFile(opsPath, 'utf8');
    ops = JSON.parse(raw);
    if (!Array.isArray(ops)) ops = [];
  } catch (err) {
    if (err.code !== 'ENOENT') {
      console.warn(`[world-reset] Warning: could not read ops.json: ${err.message}`);
    }
    ops = [];
  }

  const already = ops.some((entry) => entry.name === username);
  if (already) {
    console.log(`[world-reset] "${username}" already in ops.json`);
    return;
  }

  const uuid = offlineUuidFor(username);
  ops.push({
    uuid,
    name: username,
    level: 4,
    bypassesPlayerLimit: false,
  });

  await fs.writeFile(opsPath, JSON.stringify(ops, null, 2), 'utf8');
  console.log(`[world-reset] Added "${username}" (uuid=${uuid}) to ops.json`);
}

module.exports = { resetWorld, ensureBotIsOp, offlineUuidFor };
