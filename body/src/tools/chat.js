// Tool: chat(message)
// Sends a chat message in-game via Mineflayer's bot.chat().
// Useful for debugging, demo visibility, and Reflexion narration.

const MAX_CHAT_LENGTH = 256;

async function chat(params, bot) {
  const { message } = params || {};

  if (typeof message !== 'string' || message.length === 0) {
    throw new Error('chat: message must be a non-empty string');
  }
  if (message.length > MAX_CHAT_LENGTH) {
    throw new Error(
      `chat: message exceeds ${MAX_CHAT_LENGTH} character limit (got ${message.length})`
    );
  }
  if (!bot) {
    throw new Error('chat: bot not connected');
  }

  bot.chat(message);
  return { sent: true, message };
}

module.exports = chat;
