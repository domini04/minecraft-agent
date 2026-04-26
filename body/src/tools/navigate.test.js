const navigate = require('./navigate');
const { goals } = require('mineflayer-pathfinder');

describe('navigate tool', () => {
  let mockBot;

  beforeEach(() => {
    mockBot = {
      pathfinder: { goto: jest.fn().mockResolvedValue(undefined) },
      entity: { position: { x: 10, y: 64, z: 20 } },
    };
  });

  it('T1: happy path — navigates to integer coords and returns position', async () => {
    const result = await navigate({ x: 10, y: 64, z: 20 }, mockBot);

    expect(mockBot.pathfinder.goto).toHaveBeenCalledTimes(1);
    const goalArg = mockBot.pathfinder.goto.mock.calls[0][0];
    expect(goalArg).toBeInstanceOf(goals.GoalBlock);
    expect(goalArg.x).toBe(10);
    expect(goalArg.y).toBe(64);
    expect(goalArg.z).toBe(20);
    expect(result).toEqual({ reached: true, position: { x: 10, y: 64, z: 20 } });
  });

  it('T2: float rounding — rounds coords with Math.round before constructing goal', async () => {
    // Math.round(10.7) = 11, Math.round(64.2) = 64, Math.round(20.5) = 21
    mockBot.entity.position = { x: 11, y: 64, z: 21 };

    const result = await navigate({ x: 10.7, y: 64.2, z: 20.5 }, mockBot);

    const goalArg = mockBot.pathfinder.goto.mock.calls[0][0];
    expect(goalArg).toBeInstanceOf(goals.GoalBlock);
    expect(goalArg.x).toBe(11);
    expect(goalArg.y).toBe(64);
    expect(goalArg.z).toBe(21);
    expect(result).toEqual({ reached: true, position: { x: 11, y: 64, z: 21 } });
  });

  it('T3: negative coords — accepts and passes through negative integers', async () => {
    mockBot.entity.position = { x: -50, y: 5, z: -100 };

    const result = await navigate({ x: -50, y: 5, z: -100 }, mockBot);

    const goalArg = mockBot.pathfinder.goto.mock.calls[0][0];
    expect(goalArg).toBeInstanceOf(goals.GoalBlock);
    expect(goalArg.x).toBe(-50);
    expect(goalArg.y).toBe(5);
    expect(goalArg.z).toBe(-100);
    expect(result).toEqual({ reached: true, position: { x: -50, y: 5, z: -100 } });
  });

  it('T4: missing z — throws finite number error without calling goto', async () => {
    await expect(navigate({ x: 10, y: 64 }, mockBot))
      .rejects.toThrow(/must be finite numbers/);
    expect(mockBot.pathfinder.goto).not.toHaveBeenCalled();
  });

  it('T5a: NaN x — throws finite number error without calling goto', async () => {
    await expect(navigate({ x: NaN, y: 64, z: 20 }, mockBot))
      .rejects.toThrow(/must be finite numbers/);
    expect(mockBot.pathfinder.goto).not.toHaveBeenCalled();
  });

  it('T5b: Infinity z — throws finite number error without calling goto', async () => {
    await expect(navigate({ x: 10, y: 64, z: Infinity }, mockBot))
      .rejects.toThrow(/must be finite numbers/);
    expect(mockBot.pathfinder.goto).not.toHaveBeenCalled();
  });

  it('T6: bot is null — throws bot not connected', async () => {
    await expect(navigate({ x: 10, y: 64, z: 20 }, null))
      .rejects.toThrow(/bot not connected/);
  });

  it('T7: bot.pathfinder is undefined — throws pathfinder plugin not loaded', async () => {
    const botWithoutPathfinder = { entity: { position: { x: 10, y: 64, z: 20 } } };
    await expect(navigate({ x: 10, y: 64, z: 20 }, botWithoutPathfinder))
      .rejects.toThrow(/pathfinder plugin not loaded/);
  });

  it('T8: goto rejects — wraps error with pathfinding failed prefix', async () => {
    mockBot.pathfinder.goto.mockRejectedValueOnce(new Error('NoPath'));
    await expect(navigate({ x: 10, y: 64, z: 20 }, mockBot))
      .rejects.toThrow(/navigate: pathfinding failed: NoPath/);
  });
});
