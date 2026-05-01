// Mineflayer bot module
// Creates and configures the Minecraft bot connection

const mineflayer = require('mineflayer');
const { pathfinder, Movements } = require('mineflayer-pathfinder');
const collectBlock = require('mineflayer-collectblock');

// Configuration from environment variables
const config = {
  host: process.env.MC_HOST || 'localhost',
  port: parseInt(process.env.MC_PORT, 10) || 25565,
  username: process.env.MC_USERNAME || 'agent',
};

let bot = null;

/**
 * Creates and connects the Mineflayer bot
 * @param {Object} overrides - Optional config overrides (useful for testing)
 * @returns {Object} The Mineflayer bot instance
 */
function createBot(overrides = {}) {
  const botConfig = { ...config, ...overrides };

  console.log(`[Bot] Connecting to ${botConfig.host}:${botConfig.port} as "${botConfig.username}"...`);

  bot = mineflayer.createBot({
    host: botConfig.host,
    port: botConfig.port,
    username: botConfig.username,
  });

  // Load plugins before any event handlers (D2/D3)
  bot.loadPlugin(pathfinder);
  bot.loadPlugin(collectBlock.plugin);

  // Event: Bot spawned in world
  bot.once('spawn', () => {
    console.log('[Bot] Spawned in world');
    console.log(`[Bot] Position: ${bot.entity.position}`);
    console.log(`[Bot] Health: ${bot.health}, Food: ${bot.food}`);

    // Configure default movements for pathfinder (D3)
    const movements = new Movements(bot);
    bot.pathfinder.setMovements(movements);
    console.log('[Bot] Pathfinder default Movements configured');
  });

  // Event: Bot disconnected
  bot.on('end', (reason) => {
    console.log(`[Bot] Disconnected: ${reason}`);
  });

  // Event: Bot kicked from server
  bot.on('kicked', (reason, loggedIn) => {
    console.log(`[Bot] Kicked: ${reason} (loggedIn: ${loggedIn})`);
  });

  // Event: Error occurred
  bot.on('error', (err) => {
    console.error(`[Bot] Error: ${err.message}`);
  });

  return bot;
}

/**
 * Gets the current bot instance
 * @returns {Object|null} The bot instance or null if not created
 */
function getBot() {
  return bot;
}

/**
 * Gets structured bot status for the /status endpoint
 * @returns {Object|null} Bot status object or null if bot not connected
 */
function getBotStatus() {
  if (!bot || !bot.entity) {
    return null;
  }

  const pos = bot.entity.position;

  // Build inventory list from bot.inventory.items()
  const inventory = bot.inventory
    ? bot.inventory.items().map((item) => ({
        name: item.name,
        count: item.count,
      }))
    : [];

  // Get nearby entities (excluding the bot itself)
  const nearbyEntities = Object.values(bot.entities)
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
    nearby_entities: nearbyEntities,
  };
}

/**
 * Disconnects the bot gracefully
 */
function disconnectBot() {
  if (bot) {
    console.log('[Bot] Disconnecting...');
    bot.quit();
    bot = null;
  }
}

// Graceful shutdown on process exit (only register once)
if (!process.env.JEST_WORKER_ID) {
  process.on('SIGINT', () => {
    disconnectBot();
    process.exit(0);
  });

  process.on('SIGTERM', () => {
    disconnectBot();
    process.exit(0);
  });
}

module.exports = {
  createBot,
  getBot,
  getBotStatus,
  disconnectBot,
  config,
};
