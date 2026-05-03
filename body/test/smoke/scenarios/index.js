// Ordered list of smoke-test scenarios.
// Order is significant: 04-mine consumes the dirt placed by 03-place-block.

module.exports = [
  require('./00-chat'),
  require('./01-get-bot-status'),
  require('./02-navigate'),
  require('./03-place-block'),
  require('./04-mine'),
  require('./05-craft'),
];
