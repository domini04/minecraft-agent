const mine = require('./mine');

describe('mine tool', () => {
  const mockBlock = (name = 'oak_log', pos = { x: 5, y: 64, z: 5 }) =>
    ({ name, position: pos });

  const makeMockBot = () => {
    let targetCount = 0;
    const bot = {
      registry: { blocksByName: { oak_log: { id: 17, name: 'oak_log' } } },
      findBlock: jest.fn(),
      collectBlock: {
        collect: jest.fn().mockImplementation(async () => { targetCount += 1; }),
      },
      inventory: {
        items: jest.fn(() => Array(targetCount).fill({ name: 'oak_log', count: 1 })),
      },
      entity: { position: { x: 5, y: 64, z: 5 } },
    };
    // Expose counter mutator for tests that override collect.mockImplementation
    bot._bumpTarget = () => { targetCount += 1; };
    return bot;
  };

  // T1: Happy path — mines 1 block, returns correct shape
  it('T1: mines 1 block and returns correct result shape', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock.mockReturnValueOnce(mockBlock());

    const result = await mine({ target: 'oak_log', count: 1 }, mockBot);

    expect(result).toEqual({
      items_collected: 1,
      item_type: 'oak_log',
      last_position: { x: 5, y: 64, z: 5 },
    });
    expect(mockBot.findBlock).toHaveBeenCalledTimes(1);
    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(1);
  });

  // T2: Multi-block success — mines count=3, last_position reflects position after final collect
  it('T2: mines 3 blocks and returns items_collected=3 with final position', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock
      .mockReturnValueOnce(mockBlock('oak_log', { x: 1, y: 64, z: 1 }))
      .mockReturnValueOnce(mockBlock('oak_log', { x: 2, y: 64, z: 2 }))
      .mockReturnValueOnce(mockBlock('oak_log', { x: 3, y: 64, z: 3 }));

    // Simulate bot position changing as it mines each block
    let callCount = 0;
    mockBot.collectBlock.collect.mockImplementation(async () => {
      callCount += 1;
      mockBot._bumpTarget();
      mockBot.entity.position = { x: callCount, y: 64, z: callCount };
    });

    const result = await mine({ target: 'oak_log', count: 3 }, mockBot);

    expect(result).toEqual({
      items_collected: 3,
      item_type: 'oak_log',
      last_position: { x: 3, y: 64, z: 3 },
    });
    expect(mockBot.findBlock).toHaveBeenCalledTimes(3);
    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(3);
  });

  // T3: findBlock returns null on first call — throws with "collected 0 of N"
  it('T3: throws when no block found on first iteration (collected 0 of 5)', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock.mockReturnValue(null);

    await expect(mine({ target: 'oak_log', count: 5 }, mockBot))
      .rejects.toThrow(/mine: no oak_log within 32 blocks \(collected 0 of 5\)/);

    expect(mockBot.collectBlock.collect).not.toHaveBeenCalled();
    expect(mockBot.findBlock).toHaveBeenCalledTimes(1);
  });

  // T4: findBlock returns null mid-loop — throws with correct "collected 2 of 5"
  it('T4: throws mid-loop when block not found (collected 2 of 5), collect not called on failing iteration', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock
      .mockReturnValueOnce(mockBlock())
      .mockReturnValueOnce(mockBlock())
      .mockReturnValueOnce(null);

    await expect(mine({ target: 'oak_log', count: 5 }, mockBot))
      .rejects.toThrow(/mine: no oak_log within 32 blocks \(collected 2 of 5\)/);

    expect(mockBot.findBlock).toHaveBeenCalledTimes(3);
    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(2);
  });

  // T5: collect() rejects — throws wrapped error and does not call findBlock again
  it('T5: throws collect failed when collect() rejects, loop exits immediately', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock.mockReturnValueOnce(mockBlock());
    mockBot.collectBlock.collect.mockRejectedValueOnce(new Error('Inventory full'));

    await expect(mine({ target: 'oak_log', count: 3 }, mockBot))
      .rejects.toThrow(/mine: collect failed: Inventory full/);

    expect(mockBot.findBlock).toHaveBeenCalledTimes(1);
    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(1);
  });

  // T6: Param validation — missing/empty/non-string target; count=0, -1, float, NaN, string
  it('T6a: throws when target is missing', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ count: 1 }, mockBot))
      .rejects.toThrow(/mine: target must be a non-empty string/);
  });

  it('T6b: throws when target is empty string', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: '', count: 1 }, mockBot))
      .rejects.toThrow(/mine: target must be a non-empty string/);
  });

  it('T6c: throws when target is a number', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 42, count: 1 }, mockBot))
      .rejects.toThrow(/mine: target must be a non-empty string/);
  });

  it('T6d: throws when count is 0', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 0 }, mockBot))
      .rejects.toThrow(/mine: count must be a positive integer/);
  });

  it('T6e: throws when count is -1', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: -1 }, mockBot))
      .rejects.toThrow(/mine: count must be a positive integer/);
  });

  it('T6f: throws when count is a float (1.5)', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 1.5 }, mockBot))
      .rejects.toThrow(/mine: count must be a positive integer/);
  });

  it('T6g: throws when count is a string', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 'abc' }, mockBot))
      .rejects.toThrow(/mine: count must be a positive integer/);
  });

  it('T6h: throws when count is NaN', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: NaN }, mockBot))
      .rejects.toThrow(/mine: count must be a positive integer/);
  });

  it('T6i: throws when max_distance is 0', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 1, max_distance: 0 }, mockBot))
      .rejects.toThrow(/mine: max_distance must be an integer between 1 and 128/);
  });

  it('T6j: throws when max_distance is 129', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 1, max_distance: 129 }, mockBot))
      .rejects.toThrow(/mine: max_distance must be an integer between 1 and 128/);
  });

  it('T6k: throws when max_distance is a float', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 1, max_distance: 1.5 }, mockBot))
      .rejects.toThrow(/mine: max_distance must be an integer between 1 and 128/);
  });

  it('T6l: throws when max_distance is a string', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'oak_log', count: 1, max_distance: 'foo' }, mockBot))
      .rejects.toThrow(/mine: max_distance must be an integer between 1 and 128/);
  });

  // T7: Unknown block name throws appropriate error
  it('T7: throws for unknown block name', async () => {
    const mockBot = makeMockBot();
    await expect(mine({ target: 'unknown_block', count: 1 }, mockBot))
      .rejects.toThrow(/mine: unknown block name "unknown_block" \(no entry in bot\.registry\.blocksByName\)/);
  });

  // T8: Bot null / collectBlock missing / findBlock missing / registry missing
  it('T8: throws when bot is null', async () => {
    await expect(mine({ target: 'oak_log', count: 1 }, null))
      .rejects.toThrow(/mine: bot not connected/);
  });

  it('T9a: throws when collectBlock plugin is missing', async () => {
    const mockBot = makeMockBot();
    delete mockBot.collectBlock;
    await expect(mine({ target: 'oak_log', count: 1 }, mockBot))
      .rejects.toThrow(/mine: collectblock plugin not loaded/);
  });

  it('T9b: throws when findBlock is missing', async () => {
    const mockBot = makeMockBot();
    delete mockBot.findBlock;
    await expect(mine({ target: 'oak_log', count: 1 }, mockBot))
      .rejects.toThrow(/mine: findBlock not available \(bot not spawned\?\)/);
  });

  it('T9c: throws when registry is missing', async () => {
    const mockBot = makeMockBot();
    delete mockBot.registry;
    await expect(mine({ target: 'oak_log', count: 1 }, mockBot))
      .rejects.toThrow(/mine: bot registry not available \(bot not spawned\?\)/);
  });

  // T10: max_distance defaults to 32 when omitted; explicit value forwarded correctly
  it('T10a: max_distance defaults to 32 when not provided', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock.mockReturnValueOnce(mockBlock());

    await mine({ target: 'oak_log', count: 1 }, mockBot);

    expect(mockBot.findBlock.mock.calls[0][0].maxDistance).toBe(32);
  });

  it('T10b: explicit max_distance is forwarded to findBlock', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock.mockReturnValueOnce(mockBlock());

    await mine({ target: 'oak_log', count: 1, max_distance: 64 }, mockBot);

    expect(mockBot.findBlock.mock.calls[0][0].maxDistance).toBe(64);
  });

  // T11: Happy path with inventory verification active — collect succeeds and inventory grows
  it('T11: happy path with verification — count=2, inventory grows by 1 each collect', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock
      .mockReturnValueOnce(mockBlock())
      .mockReturnValueOnce(mockBlock());

    const result = await mine({ target: 'oak_log', count: 2 }, mockBot);

    expect(result).toEqual({
      items_collected: 2,
      item_type: 'oak_log',
      last_position: { x: 5, y: 64, z: 5 },
    });
    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(2);
    expect(mockBot.inventory.items).toHaveBeenCalled();
  });

  // T12: collect resolves on iteration 0 but inventory unchanged — throws with correct message
  it('T12: throws when collect resolves but inventory does not increase (iteration 0)', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock.mockReturnValueOnce(mockBlock());
    // Override collect to NOT bump inventory
    mockBot.collectBlock.collect.mockResolvedValue(undefined);

    await expect(mine({ target: 'oak_log', count: 1 }, mockBot))
      .rejects.toThrow(
        /mine: collect resolved but inventory did not increase for "oak_log" \(collected 0 of 1 dug-and-resolved; possible pickup race\)/
      );

    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(1);
  });

  // T13: mid-loop pickup failure — first 2 of 3 collects grow inventory, 3rd does not
  it('T13: throws mid-loop when 3rd collect resolves but inventory does not increase (collected 2 of 3)', async () => {
    const mockBot = makeMockBot();
    mockBot.findBlock
      .mockReturnValueOnce(mockBlock())
      .mockReturnValueOnce(mockBlock())
      .mockReturnValueOnce(mockBlock());

    let callCount = 0;
    mockBot.collectBlock.collect.mockImplementation(async () => {
      callCount += 1;
      // Only bump inventory for first 2 calls; 3rd call resolves without pickup
      if (callCount <= 2) {
        mockBot._bumpTarget();
      }
    });

    await expect(mine({ target: 'oak_log', count: 3 }, mockBot))
      .rejects.toThrow(
        /mine: collect resolved but inventory did not increase for "oak_log" \(collected 2 of 3 dug-and-resolved; possible pickup race\)/
      );

    expect(mockBot.findBlock).toHaveBeenCalledTimes(3);
    expect(mockBot.collectBlock.collect).toHaveBeenCalledTimes(3);
  });
});
