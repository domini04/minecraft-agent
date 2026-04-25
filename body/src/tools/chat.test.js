const chat = require('./chat');

describe('chat tool', () => {
  let mockBot;

  beforeEach(() => {
    mockBot = { chat: jest.fn() };
  });

  it('T1: sends message and returns confirmation', async () => {
    await expect(chat({ message: 'hi' }, mockBot))
      .resolves.toEqual({ sent: true, message: 'hi' });
    expect(mockBot.chat).toHaveBeenCalledTimes(1);
    expect(mockBot.chat).toHaveBeenCalledWith('hi');
  });

  it('T2: throws on empty message', async () => {
    await expect(chat({ message: '' }, mockBot))
      .rejects.toThrow(/must be a non-empty string/);
    expect(mockBot.chat).not.toHaveBeenCalled();
  });

  it('T3: throws when message field is missing', async () => {
    await expect(chat({}, mockBot))
      .rejects.toThrow(/must be a non-empty string/);
    expect(mockBot.chat).not.toHaveBeenCalled();
  });

  it('T4: throws on non-string message', async () => {
    await expect(chat({ message: 42 }, mockBot))
      .rejects.toThrow(/must be a non-empty string/);
    expect(mockBot.chat).not.toHaveBeenCalled();
  });

  it('T5: throws when bot is not connected (null)', async () => {
    await expect(chat({ message: 'hi' }, null))
      .rejects.toThrow(/bot not connected/);
  });

  it('T6: throws when message exceeds 256 character limit', async () => {
    await expect(chat({ message: 'a'.repeat(257) }, mockBot))
      .rejects.toThrow(/256 character limit/);
    expect(mockBot.chat).not.toHaveBeenCalled();
  });
});
