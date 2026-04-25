// Tool dispatch map.
// Maps tool name strings to their handler functions.
// To add a tool: create tools/<name>.js and add one line here.

module.exports = {
  mine:           require('./mine'),
  craft:          require('./craft'),
  place_block:    require('./place_block'),
  navigate:       require('./navigate'),
  get_bot_status: require('./get_bot_status'),
  chat:           require('./chat'),
};
