// Server entry point
// Starts Express server and connects Mineflayer bot

const app = require('./app');
const { createBot } = require('./bot');

const HOST = process.env.BOT_HOST || '127.0.0.1';
const PORT = process.env.BOT_PORT || 3000;

// Start Express server
app.listen(PORT, HOST, () => {
  console.log(`[Body] Listening on ${HOST}:${PORT}`);

  // Connect to Minecraft after Express is ready
  createBot();
});
