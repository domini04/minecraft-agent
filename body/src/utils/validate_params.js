// JSON-Schema-driven param validator for the six body tools.
//
// Loads the canonical schemas from `shared/tool-schemas/` at module-load,
// compiles them once with ajv (Draft 2020-12), and exposes
// `validateParams(toolName, params)` which throws a `ValidationError`
// (with `.code === 'INVALID_PARAMS'`) when validation fails.
//
// Error messages are translated from ajv's structured errors back into
// the legacy per-tool strings the existing tool tests assert via regex,
// so this refactor is constraint- and message-preserving.
//
// NaN/Infinity caveat: ajv's `type: "number"` accepts non-finite numbers
// (since `typeof NaN === 'number'`), but the legacy validators reject
// them via `Number.isFinite`. We enforce that as a post-pass for
// `navigate` and `place_block`.

const path = require('path');
const Ajv2020 = require('ajv/dist/2020');

const SCHEMA_DIR = path.resolve(__dirname, '../../../shared/tool-schemas');
const index = require(path.join(SCHEMA_DIR, 'index.json'));

// useDefaults: false — schemas describe shape, not behavior. The JS-side
// `mine.max_distance` default stays in mine.js (option 1 from the plan).
const ajv = new Ajv2020({ allErrors: true, useDefaults: false, strict: true });

const validators = {};
for (const [tool, file] of Object.entries(index)) {
  // eslint-disable-next-line global-require, import/no-dynamic-require
  const schema = require(path.join(SCHEMA_DIR, file));
  validators[tool] = ajv.compile(schema);
}

class ValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ValidationError';
    this.code = 'INVALID_PARAMS';
  }
}

// --- Translation tables ---
//
// Each entry maps (instancePath, keyword) → legacy message string OR a
// function (err, params) → string. Required-property errors are
// dispatched on (`'', 'required', missingProperty`).

const MSG_CHAT_NON_EMPTY_STRING = 'chat: message must be a non-empty string';
const MSG_NAVIGATE_FINITE       = 'navigate: x, y, z must be finite numbers';
const MSG_PLACE_BLOCK_NES       = 'place_block: block must be a non-empty string';
const MSG_PLACE_BLOCK_FINITE    = 'place_block: x, y, z must be finite numbers';
const MSG_MINE_TARGET_NES       = 'mine: target must be a non-empty string';
const MSG_MINE_COUNT_POS_INT    = 'mine: count must be a positive integer';
const MSG_MINE_MAX_DIST_RANGE   = 'mine: max_distance must be an integer between 1 and 128';
const MSG_CRAFT_ITEM_NES        = 'craft: item must be a non-empty string';
const MSG_CRAFT_COUNT_POS_INT   = 'craft: count must be a positive integer';
const MSG_CRAFT_TABLE_POS       = 'craft: crafting_table_pos must be {x, y, z} integers';

// `key` for direct-keyword errors is `${instancePath}:${keyword}`.
// For required errors, `key` is `required:${missingProperty}` (since
// instancePath is '' for top-level required).
const TRANSLATIONS = {
  chat: {
    'required:message':   MSG_CHAT_NON_EMPTY_STRING,
    '/message:type':      MSG_CHAT_NON_EMPTY_STRING,
    '/message:minLength': MSG_CHAT_NON_EMPTY_STRING,
    '/message:maxLength': (err, params) =>
      `chat: message exceeds 256 character limit (got ${
        typeof params.message === 'string' ? params.message.length : 'n/a'
      })`,
  },

  get_bot_status: {
    // No fields required; only additionalProperties violations are possible.
    // No legacy message exists for that case, so the generic ajv string is
    // fine; we still tag it as INVALID_PARAMS via ValidationError.
  },

  navigate: {
    'required:x': MSG_NAVIGATE_FINITE,
    'required:y': MSG_NAVIGATE_FINITE,
    'required:z': MSG_NAVIGATE_FINITE,
    '/x:type':    MSG_NAVIGATE_FINITE,
    '/y:type':    MSG_NAVIGATE_FINITE,
    '/z:type':    MSG_NAVIGATE_FINITE,
  },

  mine: {
    'required:target':       MSG_MINE_TARGET_NES,
    '/target:type':          MSG_MINE_TARGET_NES,
    '/target:minLength':     MSG_MINE_TARGET_NES,
    '/target:pattern':       MSG_MINE_TARGET_NES,
    'required:count':        MSG_MINE_COUNT_POS_INT,
    '/count:type':           MSG_MINE_COUNT_POS_INT,
    '/count:minimum':        MSG_MINE_COUNT_POS_INT,
    '/max_distance:type':    MSG_MINE_MAX_DIST_RANGE,
    '/max_distance:minimum': MSG_MINE_MAX_DIST_RANGE,
    '/max_distance:maximum': MSG_MINE_MAX_DIST_RANGE,
  },

  craft: {
    'required:item':                  MSG_CRAFT_ITEM_NES,
    '/item:type':                     MSG_CRAFT_ITEM_NES,
    '/item:minLength':                MSG_CRAFT_ITEM_NES,
    '/item:pattern':                  MSG_CRAFT_ITEM_NES,
    'required:count':                 MSG_CRAFT_COUNT_POS_INT,
    '/count:type':                    MSG_CRAFT_COUNT_POS_INT,
    '/count:minimum':                 MSG_CRAFT_COUNT_POS_INT,
    // crafting_table_pos issues — any sub-field problem maps to the legacy
    // "must be {x, y, z} integers" message.
    '/crafting_table_pos:type':       MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos:required':   MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos/x:type':     MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos/y:type':     MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos/z:type':     MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos/x:required': MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos/y:required': MSG_CRAFT_TABLE_POS,
    '/crafting_table_pos/z:required': MSG_CRAFT_TABLE_POS,
  },

  place_block: {
    'required:block':    MSG_PLACE_BLOCK_NES,
    '/block:type':       MSG_PLACE_BLOCK_NES,
    '/block:minLength':  MSG_PLACE_BLOCK_NES,
    '/block:pattern':    MSG_PLACE_BLOCK_NES,
    'required:x':        MSG_PLACE_BLOCK_FINITE,
    'required:y':        MSG_PLACE_BLOCK_FINITE,
    'required:z':        MSG_PLACE_BLOCK_FINITE,
    '/x:type':           MSG_PLACE_BLOCK_FINITE,
    '/y:type':           MSG_PLACE_BLOCK_FINITE,
    '/z:type':           MSG_PLACE_BLOCK_FINITE,
  },
};

/**
 * Build the lookup key for an ajv error. For `required` errors, ajv
 * reports the parent's instancePath plus `params.missingProperty`; we
 * encode that as `${instancePath}/required:${missing}` -- but at the
 * top level instancePath is '' so we get `required:${missing}`.
 */
function lookupKey(err) {
  if (err.keyword === 'required') {
    const parent = err.instancePath || '';
    const missing = err.params && err.params.missingProperty;
    if (parent === '') {
      return `required:${missing}`;
    }
    return `${parent}/${missing}:required`;
  }
  return `${err.instancePath}:${err.keyword}`;
}

/**
 * Translate ajv errors to the legacy single-string error message for a
 * given tool. Returns the first translatable message; if no translation
 * matches, falls back to a synthesised "<tool>: <key> <ajv message>"
 * string so that schema-author mistakes are still surfaced.
 */
function translate(toolName, errors, params) {
  const table = TRANSLATIONS[toolName] || {};
  for (const err of errors) {
    const key = lookupKey(err);
    const entry = table[key];
    if (typeof entry === 'function') return entry(err, params);
    if (typeof entry === 'string')   return entry;
  }
  // Fallback (covers e.g. additionalProperties violations or any
  // schema/test drift the table did not anticipate).
  const first = errors[0];
  return `${toolName}: ${first.instancePath || '(root)'} ${first.message || 'invalid'}`;
}

/**
 * Post-pass for navigate/place_block: ajv accepts NaN/Infinity as
 * `type: "number"`, but legacy semantics reject them.
 */
const NUMERIC_FINITE_FIELDS = {
  navigate:    { fields: ['x', 'y', 'z'], message: MSG_NAVIGATE_FINITE },
  place_block: { fields: ['x', 'y', 'z'], message: MSG_PLACE_BLOCK_FINITE },
};

function rejectNonFiniteNumbers(toolName, params) {
  const spec = NUMERIC_FINITE_FIELDS[toolName];
  if (!spec) return;
  for (const f of spec.fields) {
    if (params[f] !== undefined && !Number.isFinite(params[f])) {
      throw new ValidationError(spec.message);
    }
  }
}

function validateParams(toolName, params) {
  const v = validators[toolName];
  if (!v) {
    throw new Error(`validateParams: no schema registered for tool "${toolName}"`);
  }
  const ok = v(params);
  if (!ok) {
    throw new ValidationError(translate(toolName, v.errors, params));
  }
  rejectNonFiniteNumbers(toolName, params);
}

module.exports = { validateParams, ValidationError };
