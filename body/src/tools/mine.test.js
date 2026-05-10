const mine = require('./mine');
const {
  selectMineTarget,
  classifyBlock,
  TIER_LATERAL_OR_ABOVE,
  TIER_BELOW_NOT_SUPPORT,
  TIER_SUPPORT,
} = require('./mine');
const vec3 = require('vec3');

describe('mine tool', () => {
  const mockBlock = (name = 'oak_log', pos = { x: 5, y: 64, z: 5 }) =>
    ({ name, position: pos });

  // --- Sprint 3l mock-factory shim (TODO-6 path 1) ---
  //
  // The mining loop now uses bot.findBlocks (plural) + bot.blockAt instead of
  // bot.findBlock directly. To keep the existing T1..T13 assertions intact —
  // including those asserting on `mockBot.findBlock.mock.calls[0][0]` — we
  // route findBlocks/blockAt through the existing findBlock jest.fn so each
  // logical iteration still records exactly one findBlock call with the same
  // opts shape (maxDistance preserved; the additional `count` field is
  // ignored by the assertions).
  const makeMockBot = () => {
    let targetCount = 0;
    // Map block-position-reference → block, populated as findBlocks delegates
    // to the underlying findBlock and used by blockAt to resolve back.
    const posToBlock = new Map();

    const bot = {
      registry: { blocksByName: { oak_log: { id: 17, name: 'oak_log' } } },
      findBlock: jest.fn(),
      collectBlock: {
        collect: jest.fn().mockImplementation(async () => { targetCount += 1; }),
      },
      inventory: {
        items: jest.fn(() => Array(targetCount).fill({ name: 'oak_log', count: 1 })),
      },
    };

    // findBlocks shim: delegate to findBlock, return [position] array (or []).
    bot.findBlocks = jest.fn((opts) => {
      const block = bot.findBlock(opts);
      if (!block) return [];
      posToBlock.set(block.position, block);
      return [block.position];
    });

    // blockAt shim: return whatever findBlocks→findBlock yielded for that pos.
    // Falls back to a synthesized block to keep mid-loop progress sane if a
    // future test ever passes an unmapped position.
    bot.blockAt = jest.fn((pos) => {
      if (posToBlock.has(pos)) return posToBlock.get(pos);
      return { name: 'oak_log', position: pos };
    });

    // entity.position must support .floored() (vec3) because selectMineTarget
    // calls bot.entity.position.floored(). Wrap any assignment with vec3 so
    // tests that do `mockBot.entity.position = { x, y, z }` keep working.
    const entity = {};
    let _pos = vec3(5, 64, 5);
    Object.defineProperty(entity, 'position', {
      get() { return _pos; },
      set(v) {
        if (v && typeof v.floored === 'function') {
          _pos = v;
        } else {
          _pos = vec3(v.x, v.y, v.z);
        }
      },
      configurable: true,
      enumerable: true,
    });
    bot.entity = entity;

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

// ---------------------------------------------------------------------------
// Sprint 3l: tier-based block selection tests
// ---------------------------------------------------------------------------

describe('mine tool — tier selector', () => {
  // Compact mock bot for direct selectMineTarget tests. Bot stands at
  // (5.0, 70.0, 5.0) so botFloor = (5, 70, 5) and the support block is at
  // (5, 69, 5) per the locked predicate `botFloor.y - 1`.
  const makeTierBot = (candidates) => ({
    findBlocks: jest.fn(() => candidates),
    blockAt: jest.fn((pos) => ({ name: 'oak_log', position: pos })),
    entity: { position: vec3(5.0, 70.0, 5.0) },
  });

  const eq = (a, b) => a.x === b.x && a.y === b.y && a.z === b.z;

  it('tier-T1: support + 2 lateral at dist 2 → picks one of the lateral', () => {
    const support = vec3(5, 69, 5);          // Tier 2
    const lateralA = vec3(7, 70, 5);         // Tier 0, dist 2
    const lateralB = vec3(5, 70, 7);         // Tier 0, dist 2
    const bot = makeTierBot([support, lateralA, lateralB]);
    const result = selectMineTarget(bot, 17, 32);
    expect(result).not.toBeNull();
    expect(eq(result, support)).toBe(false);
    expect(eq(result, lateralA) || eq(result, lateralB)).toBe(true);
  });

  it('tier-T2: only support exists → returns the support', () => {
    const support = vec3(5, 69, 5);
    const bot = makeTierBot([support]);
    const result = selectMineTarget(bot, 17, 32);
    expect(result).not.toBeNull();
    expect(eq(result, support)).toBe(true);
  });

  it('tier-T3: lateral at dist 5, below-not-support at dist 5 → lateral wins', () => {
    const lateral = vec3(5, 70, 10);         // Tier 0, dist 5
    const belowNotSupport = vec3(10, 69, 5); // Tier 1, dist sqrt(26) ≈ 5.099
    const bot = makeTierBot([lateral, belowNotSupport]);
    const result = selectMineTarget(bot, 17, 32);
    expect(eq(result, lateral)).toBe(true);
  });

  it('tier-T4: lateral at dist 10, below-not-support at dist 5 → lateral still wins', () => {
    const lateral = vec3(5, 70, 15);         // Tier 0, dist 10 → score 10
    const belowNotSupport = vec3(10, 69, 5); // Tier 1, dist ≈ 5.099 → score ≈ 1005.099
    const bot = makeTierBot([lateral, belowNotSupport]);
    const result = selectMineTarget(bot, 17, 32);
    expect(eq(result, lateral)).toBe(true);
  });

  it('tier-T5: two lateral candidates → closer one wins', () => {
    const close = vec3(8, 70, 5);            // Tier 0, dist 3
    const far = vec3(15, 70, 5);             // Tier 0, dist 10
    const bot = makeTierBot([close, far]);
    const result = selectMineTarget(bot, 17, 32);
    expect(eq(result, close)).toBe(true);
  });

  it('tier-T6: above-dist-10 vs lateral-dist-2 → lateral wins (within Tier 0)', () => {
    const above = vec3(5, 80, 5);            // Tier 0, dist 10
    const lateral = vec3(7, 70, 5);          // Tier 0, dist 2
    const bot = makeTierBot([above, lateral]);
    const result = selectMineTarget(bot, 17, 32);
    expect(eq(result, lateral)).toBe(true);
  });

  it('tier-T7: empty candidate list → returns null', () => {
    const bot = makeTierBot([]);
    const result = selectMineTarget(bot, 17, 32);
    expect(result).toBeNull();
  });

  it('tier-classify-T8: classifyBlock matrix', () => {
    const botFloor = { x: 5, y: 70, z: 5 };
    // Support: directly under feet (botFloor.y - 1)
    expect(classifyBlock({ x: 5, y: 69, z: 5 }, botFloor)).toBe(TIER_SUPPORT);
    // Below-not-support: same y as support but different x
    expect(classifyBlock({ x: 4, y: 69, z: 5 }, botFloor)).toBe(TIER_BELOW_NOT_SUPPORT);
    // Below-not-support: deeper than support, same x/z
    expect(classifyBlock({ x: 5, y: 68, z: 5 }, botFloor)).toBe(TIER_BELOW_NOT_SUPPORT);
    // Lateral: same y as feet
    expect(classifyBlock({ x: 7, y: 70, z: 5 }, botFloor)).toBe(TIER_LATERAL_OR_ABOVE);
    // Above
    expect(classifyBlock({ x: 5, y: 71, z: 5 }, botFloor)).toBe(TIER_LATERAL_OR_ABOVE);
    // Bot's own occupied block (same as feet floor) — Tier 0 by edge-case rule
    expect(classifyBlock({ x: 5, y: 70, z: 5 }, botFloor)).toBe(TIER_LATERAL_OR_ABOVE);
  });

  it('tier-float-boundary-T9: bot at y=70.0 exactly → support is (x, 69, z)', () => {
    // With Option-A (no -0.5 offset), feet-position 70.0 floors to 70, and
    // the support predicate `botFloor.y - 1` resolves to y = 69. A candidate
    // at (5, 69, 5) must therefore be classified as TIER_SUPPORT.
    const bot = {
      findBlocks: jest.fn(() => [vec3(5, 69, 5)]),
      blockAt: jest.fn((pos) => ({ name: 'oak_log', position: pos })),
      entity: { position: vec3(5.0, 70.0, 5.0) },
    };
    const result = selectMineTarget(bot, 17, 32);
    expect(result).not.toBeNull();
    // Confirm via classifyBlock directly using the same floored position.
    const botFloor = bot.entity.position.floored();
    expect(classifyBlock({ x: 5, y: 69, z: 5 }, botFloor)).toBe(TIER_SUPPORT);
    // And the selector returned that support block (only candidate).
    expect(result.x).toBe(5);
    expect(result.y).toBe(69);
    expect(result.z).toBe(5);
  });
});
