// Mineflayer bot module
// Creates and configures the Minecraft bot connection

const mineflayer = require('mineflayer');

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

  // Event: Bot spawned in world
  bot.once('spawn', () => {
    console.log('[Bot] Spawned in world');
    console.log(`[Bot] Position: ${bot.entity.position}`);
    console.log(`[Bot] Health: ${bot.health}, Food: ${bot.food}`);
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
  disconnectBot,
  config,
};
