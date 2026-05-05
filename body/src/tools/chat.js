// Tool: chat(message)
// Sends a chat message in-game via Mineflayer's bot.chat().
// Useful for debugging, demo visibility, and Reflexion narration.

const { validateParams } = require('../utils/validate_params');

async function chat(params, bot) {
  validateParams('chat', params || {});
  const { message } = params;

  if (!bot) {
    throw new Error('chat: bot not connected');
  }

  bot.chat(message);
  return { sent: true, message };
}

module.exports = chat;
