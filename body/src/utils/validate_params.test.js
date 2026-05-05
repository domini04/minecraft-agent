const { validateParams, ValidationError } = require('./validate_params');

describe('validate_params helper', () => {
  describe('module load', () => {
    it('compiles all six tool schemas at module load (no throw)', () => {
      // If any schema failed to compile (e.g. strict-mode rejection),
      // the require() above would have thrown; reaching here is the
      // assertion. We additionally verify each tool name is dispatchable.
      for (const tool of [
        'chat',
        'get_bot_status',
        'navigate',
        'mine',
        'craft',
        'place_block',
      ]) {
        // get_bot_status accepts {} as the canonical happy path.
        // The other tools need at least the required fields below; we
        // only assert that calling validateParams does not throw an
        // "unknown tool" error for each registered tool.
        expect(() => validateParams(tool, makeHappy(tool))).not.toThrow();
      }
    });

    it('throws a non-ValidationError for an unregistered tool name', () => {
      expect(() => validateParams('not_a_tool', {})).toThrow(/no schema registered/);
    });
  });

  // --- Happy paths ---

  describe('happy paths', () => {
    it('chat: { message: "hi" } is accepted', () => {
      expect(() => validateParams('chat', { message: 'hi' })).not.toThrow();
    });

    it('get_bot_status: {} is accepted', () => {
      expect(() => validateParams('get_bot_status', {})).not.toThrow();
    });

    it('navigate: integer coords are accepted', () => {
      expect(() => validateParams('navigate', { x: 10, y: 64, z: 20 })).not.toThrow();
    });

    it('navigate: float coords are accepted (rounded later by the tool)', () => {
      expect(() => validateParams('navigate', { x: 10.7, y: 64.2, z: 20.5 })).not.toThrow();
    });

    it('mine: { target, count } without max_distance is accepted', () => {
      expect(() => validateParams('mine', { target: 'oak_log', count: 1 })).not.toThrow();
    });

    it('mine: explicit max_distance within [1,128] is accepted', () => {
      expect(() => validateParams('mine', { target: 'oak_log', count: 1, max_distance: 64 })).not.toThrow();
    });

    it('craft: 2x2 (no crafting_table_pos) is accepted', () => {
      expect(() => validateParams('craft', { item: 'stick', count: 4 })).not.toThrow();
    });

    it('craft: 3x3 with integer crafting_table_pos is accepted', () => {
      expect(() => validateParams('craft', {
        item: 'wooden_pickaxe',
        count: 1,
        crafting_table_pos: { x: 10, y: 64, z: 5 },
      })).not.toThrow();
    });

    it('place_block: { block, x, y, z } is accepted', () => {
      expect(() => validateParams('place_block', { block: 'dirt', x: 10, y: 64, z: 20 })).not.toThrow();
    });
  });

  // --- Sad paths: at least one rejection per tool, exercising the
  //     translation table back to the legacy message.

  describe('sad paths (legacy message preservation)', () => {
    const expectInvalid = (tool, params, regex) => {
      try {
        validateParams(tool, params);
        throw new Error('expected validateParams to throw');
      } catch (err) {
        expect(err).toBeInstanceOf(ValidationError);
        expect(err.code).toBe('INVALID_PARAMS');
        expect(err.message).toMatch(regex);
      }
    };

    it('chat: empty message → "must be a non-empty string"', () => {
      expectInvalid('chat', { message: '' }, /must be a non-empty string/);
    });

    it('chat: missing message → "must be a non-empty string"', () => {
      expectInvalid('chat', {}, /must be a non-empty string/);
    });

    it('chat: 257-char message → "256 character limit (got 257)"', () => {
      expectInvalid('chat', { message: 'a'.repeat(257) }, /256 character limit \(got 257\)/);
    });

    it('get_bot_status: extra prop → ValidationError (additionalProperties)', () => {
      expectInvalid('get_bot_status', { not_allowed: true }, /get_bot_status/);
    });

    it('navigate: missing z → "must be finite numbers"', () => {
      expectInvalid('navigate', { x: 10, y: 64 }, /must be finite numbers/);
    });

    it('navigate: NaN x → "must be finite numbers" (post-pass)', () => {
      expectInvalid('navigate', { x: NaN, y: 64, z: 20 }, /must be finite numbers/);
    });

    it('navigate: Infinity z → "must be finite numbers" (post-pass)', () => {
      expectInvalid('navigate', { x: 10, y: 64, z: Infinity }, /must be finite numbers/);
    });

    it('mine: target=42 → "target must be a non-empty string"', () => {
      expectInvalid('mine', { target: 42, count: 1 }, /mine: target must be a non-empty string/);
    });

    it('mine: count=0 → "count must be a positive integer"', () => {
      expectInvalid('mine', { target: 'oak_log', count: 0 }, /mine: count must be a positive integer/);
    });

    it('mine: max_distance=129 → "max_distance must be an integer between 1 and 128"', () => {
      expectInvalid('mine', { target: 'oak_log', count: 1, max_distance: 129 },
        /mine: max_distance must be an integer between 1 and 128/);
    });

    it('craft: missing item → "item must be a non-empty string"', () => {
      expectInvalid('craft', { count: 1 }, /craft: item must be a non-empty string/);
    });

    it('craft: count=1.5 → "count must be a positive integer"', () => {
      expectInvalid('craft', { item: 'stick', count: 1.5 }, /craft: count must be a positive integer/);
    });

    it('craft: crafting_table_pos missing z → "must be {x, y, z} integers"', () => {
      expectInvalid('craft',
        { item: 'stick', count: 1, crafting_table_pos: { x: 1, y: 2 } },
        /craft: crafting_table_pos must be \{x, y, z\} integers/);
    });

    it('craft: crafting_table_pos.x is float → "must be {x, y, z} integers"', () => {
      expectInvalid('craft',
        { item: 'stick', count: 1, crafting_table_pos: { x: 1.5, y: 2, z: 3 } },
        /craft: crafting_table_pos must be \{x, y, z\} integers/);
    });

    it('place_block: missing block → "block must be a non-empty string"', () => {
      expectInvalid('place_block', { x: 10, y: 64, z: 20 },
        /place_block: block must be a non-empty string/);
    });

    it('place_block: NaN x → "x, y, z must be finite numbers" (post-pass)', () => {
      expectInvalid('place_block', { block: 'dirt', x: NaN, y: 64, z: 20 },
        /place_block: x, y, z must be finite numbers/);
    });

    it('place_block: Infinity z → "x, y, z must be finite numbers" (post-pass)', () => {
      expectInvalid('place_block', { block: 'dirt', x: 10, y: 64, z: Infinity },
        /place_block: x, y, z must be finite numbers/);
    });
  });
});

// --- App-level envelope test (C8) ---
// Confirms that ValidationError thrown by a tool flows through the
// dispatcher as `error.code === 'INVALID_PARAMS'` with HTTP 200.

describe('POST /execute envelope on validation failure (C8)', () => {
  let request;
  let app;

  beforeAll(() => {
    request = require('supertest');
    jest.resetModules();
    // Mock the bot module so app.js can import without a real connection.
    jest.doMock('../bot', () => ({
      getBotStatus: jest.fn().mockReturnValue(null),
      getBot:       jest.fn().mockReturnValue({}), // truthy bot to skip the bot-null guard
    }));
    // Use the REAL tools (not mocked) so that validateParams runs.
    app = require('../app');
  });

  afterAll(() => {
    jest.dontMock('../bot');
    jest.resetModules();
  });

  it('returns INVALID_PARAMS with legacy message and HTTP 200', async () => {
    const res = await request(app)
      .post('/execute')
      .send({ tool: 'chat', params: { message: '' } });

    expect(res.status).toBe(200);
    expect(res.body.success).toBe(false);
    expect(res.body.error.code).toBe('INVALID_PARAMS');
    expect(res.body.error.message).toMatch(/chat: message must be a non-empty string/);
  });
});

// Helper used by the module-load test.
function makeHappy(tool) {
  switch (tool) {
    case 'chat':           return { message: 'ok' };
    case 'get_bot_status': return {};
    case 'navigate':       return { x: 0, y: 64, z: 0 };
    case 'mine':           return { target: 'oak_log', count: 1 };
    case 'craft':          return { item: 'stick', count: 1 };
    case 'place_block':    return { block: 'dirt', x: 0, y: 64, z: 0 };
    default:               return {};
  }
}
