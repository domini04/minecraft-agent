describe('Bot module', () => {
  let mockBot;
  let mineflayer;

  beforeEach(() => {
    // Reset modules to get fresh state each test
    jest.resetModules();

    // Create mock bot with event handling
    mockBot = {
      once: jest.fn(),
      on: jest.fn(),
      quit: jest.fn(),
      entity: { position: { x: 0, y: 64, z: 0 } },
      health: 20,
      food: 20,
    };

    // Mock mineflayer before requiring bot module
    jest.doMock('mineflayer', () => ({
      createBot: jest.fn().mockReturnValue(mockBot),
    }));

    mineflayer = require('mineflayer');
  });

  afterEach(() => {
    // Clean up env vars
    delete process.env.MC_HOST;
    delete process.env.MC_PORT;
    delete process.env.MC_USERNAME;
  });

  describe('createBot', () => {
    it('creates bot with default config', () => {
      const { createBot } = require('./bot');

      createBot();

      expect(mineflayer.createBot).toHaveBeenCalledWith({
        host: 'localhost',
        port: 25565,
        username: 'agent',
      });
    });

    it('uses environment variables when set', () => {
      process.env.MC_HOST = '192.168.1.100';
      process.env.MC_PORT = '25566';
      process.env.MC_USERNAME = 'testbot';

      // Re-require to pick up new env vars
      jest.resetModules();
      jest.doMock('mineflayer', () => ({
        createBot: jest.fn().mockReturnValue(mockBot),
      }));
      const freshMineflayer = require('mineflayer');
      const { createBot } = require('./bot');

      createBot();

      expect(freshMineflayer.createBot).toHaveBeenCalledWith({
        host: '192.168.1.100',
        port: 25566,
        username: 'testbot',
      });
    });

    it('allows config overrides', () => {
      const { createBot } = require('./bot');

      createBot({ username: 'custom-bot', port: 12345 });

      expect(mineflayer.createBot).toHaveBeenCalledWith({
        host: 'localhost',
        port: 12345,
        username: 'custom-bot',
      });
    });

    it('registers spawn event handler', () => {
      const { createBot } = require('./bot');

      createBot();

      expect(mockBot.once).toHaveBeenCalledWith('spawn', expect.any(Function));
    });

    it('registers error event handler', () => {
      const { createBot } = require('./bot');

      createBot();

      expect(mockBot.on).toHaveBeenCalledWith('error', expect.any(Function));
    });

    it('registers end event handler', () => {
      const { createBot } = require('./bot');

      createBot();

      expect(mockBot.on).toHaveBeenCalledWith('end', expect.any(Function));
    });

    it('registers kicked event handler', () => {
      const { createBot } = require('./bot');

      createBot();

      expect(mockBot.on).toHaveBeenCalledWith('kicked', expect.any(Function));
    });
  });

  describe('getBot', () => {
    it('returns null before bot is created', () => {
      const { getBot } = require('./bot');

      expect(getBot()).toBeNull();
    });

    it('returns bot instance after creation', () => {
      const { createBot, getBot } = require('./bot');

      createBot();

      expect(getBot()).toBe(mockBot);
    });
  });

  describe('disconnectBot', () => {
    it('calls bot.quit when bot exists', () => {
      const { createBot, disconnectBot } = require('./bot');

      createBot();
      disconnectBot();

      expect(mockBot.quit).toHaveBeenCalled();
    });

    it('does nothing when bot does not exist', () => {
      const { disconnectBot } = require('./bot');

      // Should not throw
      expect(() => disconnectBot()).not.toThrow();
    });
  });
});
