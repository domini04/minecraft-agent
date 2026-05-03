// T1 — chat scenario
// Sends a smoke-test chat message and verifies the envelope shape.

const { assertEnvelope } = require('../assertions');

module.exports = {
  name: 'chat',

  async run(ctx) {
    const message = `smoke-test-${ctx.runId}`;
    const env = await ctx.client.execute('chat', { message });

    assertEnvelope(env, { tool: 'chat', success: true });

    if (env.data.sent !== true) {
      throw new Error(`chat: expected data.sent === true, got ${env.data.sent}`);
    }
    if (env.data.message !== message) {
      throw new Error(`chat: expected data.message === "${message}", got "${env.data.message}"`);
    }

    return env;
  },
};
