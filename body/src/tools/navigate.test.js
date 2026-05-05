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
    expect(goalArg).toBeInstanceOf(goals.GoalNear);
    expect(goalArg.rangeSq).toBe(1);
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
    expect(goalArg).toBeInstanceOf(goals.GoalNear);
    expect(goalArg.rangeSq).toBe(1);
    expect(goalArg.x).toBe(11);
    expect(goalArg.y).toBe(64);
    expect(goalArg.z).toBe(21);
    expect(result).toEqual({ reached: true, position: { x: 11, y: 64, z: 21 } });
  });

  it('T3: negative coords — accepts and passes through negative integers', async () => {
    mockBot.entity.position = { x: -50, y: 5, z: -100 };

    const result = await navigate({ x: -50, y: 5, z: -100 }, mockBot);

    const goalArg = mockBot.pathfinder.goto.mock.calls[0][0];
    expect(goalArg).toBeInstanceOf(goals.GoalNear);
    expect(goalArg.rangeSq).toBe(1);
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

  describe('T9: thinkTimeout save-and-restore', () => {
    it('T9a: success path — sets thinkTimeout during goto, restores prior value after', async () => {
      mockBot.pathfinder.thinkTimeout = 5000;

      let capturedDuringGoto;
      mockBot.pathfinder.goto.mockImplementation(async () => {
        capturedDuringGoto = mockBot.pathfinder.thinkTimeout;
      });

      await navigate({ x: 10, y: 64, z: 20 }, mockBot);

      // During goto, thinkTimeout must be the navigate budget (20000 ms by default)
      expect(capturedDuringGoto).toBe(20000);
      // After goto resolves, thinkTimeout must be restored to the prior value
      expect(mockBot.pathfinder.thinkTimeout).toBe(5000);
    });

    it('T9b: failure path — restores thinkTimeout even when goto rejects', async () => {
      mockBot.pathfinder.thinkTimeout = 5000;

      let capturedDuringGoto;
      mockBot.pathfinder.goto.mockImplementation(async () => {
        capturedDuringGoto = mockBot.pathfinder.thinkTimeout;
        throw new Error('Took to long to decide path to goal!');
      });

      await expect(navigate({ x: 10, y: 64, z: 20 }, mockBot))
        .rejects.toThrow(/navigate: pathfinding failed/);

      // During goto, thinkTimeout must be the navigate budget
      expect(capturedDuringGoto).toBe(20000);
      // After goto rejects, thinkTimeout must still be restored
      expect(mockBot.pathfinder.thinkTimeout).toBe(5000);
    });
  });
});
