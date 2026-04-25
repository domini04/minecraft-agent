const request = require('supertest');

// Mock bot module before importing app
jest.mock('./bot');
const { getBotStatus, getBot } = require('./bot');
const mockBotInstance = { health: 20 };

// Mock tools so tests don't depend on Mineflayer implementations
jest.mock('./tools/index', () => ({
  mine:           jest.fn(),
  craft:          jest.fn(),
  place_block:    jest.fn(),
  navigate:       jest.fn(),
  get_bot_status: jest.fn(),
  chat:           jest.fn(),
}));
const tools = require('./tools/index');

const app = require('./app');

describe('GET /status', () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it('returns ok with bot data when bot is connected', async () => {
    getBotStatus.mockReturnValue({
      health: 20,
      food: 18,
      position: { x: -37.5, y: 71, z: 48.5 },
      inventory: [{ name: 'oak_log', count: 3 }],
      nearby_entities: [],
    });

    const response = await request(app)
      .get('/status')
      .expect('Content-Type', /json/)
      .expect(200);

    expect(response.body.ok).toBe(true);
    expect(response.body.bot).toEqual({
      health: 20,
      food: 18,
      position: { x: -37.5, y: 71, z: 48.5 },
      inventory: [{ name: 'oak_log', count: 3 }],
      nearby_entities: [],
    });
  });

  it('returns ok with bot: null when bot is not connected', async () => {
    getBotStatus.mockReturnValue(null);

    const response = await request(app)
      .get('/status')
      .expect('Content-Type', /json/)
      .expect(200);

    expect(response.body.ok).toBe(true);
    expect(response.body.bot).toBeNull();
  });

  it('returns ok with bot: null when bot has no entity yet', async () => {
    getBotStatus.mockReturnValue(null);

    const response = await request(app)
      .get('/status')
      .expect(200);

    expect(response.body).toEqual({ ok: true, bot: null });
  });
});

describe('POST /execute', () => {
  beforeEach(() => {
    getBot.mockReturnValue(mockBotInstance);
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  describe('validation', () => {
    it('returns 400 when tool field is missing', async () => {
      const res = await request(app)
        .post('/execute')
        .send({ params: { count: 5 } })
        .expect(400);

      expect(res.body.success).toBe(false);
      expect(res.body.error.code).toBe('INVALID_PARAMS');
    });

    it('returns 400 when tool field is empty string', async () => {
      const res = await request(app)
        .post('/execute')
        .send({ tool: '', params: {} })
        .expect(400);

      expect(res.body.success).toBe(false);
      expect(res.body.error.code).toBe('INVALID_PARAMS');
    });

    it('returns 400 with UNKNOWN_TOOL for unregistered tool names', async () => {
      const res = await request(app)
        .post('/execute')
        .send({ tool: 'fly', params: {} })
        .expect(400);

      expect(res.body.success).toBe(false);
      expect(res.body.error.code).toBe('UNKNOWN_TOOL');
      expect(res.body.error.context.available).toEqual(
        expect.arrayContaining(['mine', 'craft', 'navigate'])
      );
    });
  });

  describe('dispatch', () => {
    it('dispatches to the correct handler and returns success', async () => {
      tools.mine.mockResolvedValue({ items_collected: 5, item_type: 'oak_log' });

      const res = await request(app)
        .post('/execute')
        .send({ tool: 'mine', params: { target: 'oak_log', count: 5 } })
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.tool).toBe('mine');
      expect(res.body.data).toEqual({ items_collected: 5, item_type: 'oak_log' });
      expect(typeof res.body.duration_ms).toBe('number');
    });

    it('returns ACTION_FAILED when handler throws', async () => {
      tools.craft.mockRejectedValue(new Error('NOT_IMPLEMENTED: craft'));

      const res = await request(app)
        .post('/execute')
        .send({ tool: 'craft', params: { item: 'oak_planks' } })
        .expect(200);

      expect(res.body.success).toBe(false);
      expect(res.body.tool).toBe('craft');
      expect(res.body.error.code).toBe('ACTION_FAILED');
    });

    it('passes params and bot to the handler', async () => {
      tools.navigate.mockResolvedValue({ reached: true });

      await request(app)
        .post('/execute')
        .send({ tool: 'navigate', params: { x: 10, y: 64, z: 20 } });

      expect(tools.navigate).toHaveBeenCalledWith(
        { x: 10, y: 64, z: 20 },
        expect.anything() // bot instance (null in tests since bot is mocked)
      );
    });

    it('defaults params to {} when omitted', async () => {
      tools.chat.mockResolvedValue({ sent: true });

      await request(app)
        .post('/execute')
        .send({ tool: 'chat' });

      expect(tools.chat).toHaveBeenCalledWith({}, expect.anything());
    });
  });

  describe('response shape', () => {
    it('success response includes success, data, tool, duration_ms', async () => {
      tools.mine.mockResolvedValue({ items_collected: 1 });

      const res = await request(app)
        .post('/execute')
        .send({ tool: 'mine', params: {} });

      expect(res.body).toMatchObject({
        success: true,
        tool: 'mine',
        data: { items_collected: 1 },
      });
      expect(typeof res.body.duration_ms).toBe('number');
    });

    it('error response includes success, error.code, error.message, tool, duration_ms', async () => {
      tools.mine.mockRejectedValue(new Error('something went wrong'));

      const res = await request(app)
        .post('/execute')
        .send({ tool: 'mine', params: {} });

      expect(res.body).toMatchObject({
        success: false,
        tool: 'mine',
        error: {
          code: 'ACTION_FAILED',
          message: 'something went wrong',
        },
      });
      expect(typeof res.body.duration_ms).toBe('number');
    });
  });
});

describe('Unknown routes', () => {
  it('returns 404 for GET to unknown path', async () => {
    const response = await request(app)
      .get('/nonexistent')
      .expect('Content-Type', /json/)
      .expect(404);

    expect(response.body.success).toBe(false);
    expect(response.body.error.code).toBe('NOT_FOUND');
  });

  it('returns 404 for POST to unknown path', async () => {
    const response = await request(app)
      .post('/nonexistent')
      .send({ foo: 'bar' })
      .expect(404);

    expect(response.body.error.code).toBe('NOT_FOUND');
  });
});
