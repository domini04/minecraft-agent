const place_block = require('./place_block');
const { goals } = require('mineflayer-pathfinder');

describe('place_block tool', () => {
  // Builds a fresh mock bot for each test (A7 — no shared state).
  const makeMockBot = () => ({
    registry: {
      itemsByName: {
        crafting_table: { id: 58, name: 'crafting_table' },
        dirt: { id: 3, name: 'dirt' },
      },
    },
    blockAt: jest.fn(),
    pathfinder: { goto: jest.fn().mockResolvedValue(undefined) },
    inventory: { items: jest.fn().mockReturnValue([]) },
    equip: jest.fn().mockResolvedValue(undefined),
    placeBlock: jest.fn().mockResolvedValue(undefined),
    entity: { position: { x: 0, y: 64, z: 0 } },
  });

  // Helper: wire bot.blockAt using a position-keyed map.
  // Keys are '${x},${y},${z}'; unlisted positions return null.
  const blockAtFromMap = (mapEntries) => (vec) => {
    const key = `${vec.x},${vec.y},${vec.z}`;
    return mapEntries[key] ?? null;
  };

  // T1: Happy path — target air, solid neighbor below (dirt), integer coords
  it('T1: places block on solid neighbor below, returns correct shape and calls are correct', async () => {
    const bot = makeMockBot();
    const tx = 10, ty = 64, tz = 20;

    // Target (10,64,20) is air; neighbor below (10,63,20) is dirt
    const dirtBlock = { name: 'dirt' };
    bot.blockAt.mockImplementation(blockAtFromMap({
      [`${tx},${ty},${tz}`]:     { name: 'air' },
      [`${tx},${ty - 1},${tz}`]: dirtBlock,
    }));

    const craftingTableItem = { name: 'crafting_table', count: 1 };
    bot.inventory.items.mockReturnValue([craftingTableItem]);

    const result = await place_block({ block: 'crafting_table', x: tx, y: ty, z: tz }, bot);

    // C10: return shape
    expect(result).toEqual({ placed: true, block: 'crafting_table', position: { x: 10, y: 64, z: 20 } });

    // C6: GoalNear with rounded coords and rangeSq === 9 (range 3)
    expect(bot.pathfinder.goto).toHaveBeenCalledTimes(1);
    const goalArg = bot.pathfinder.goto.mock.calls[0][0];
    expect(goalArg).toBeInstanceOf(goals.GoalNear);
    expect(goalArg.x).toBe(10);
    expect(goalArg.y).toBe(64);
    expect(goalArg.z).toBe(20);
    expect(goalArg.rangeSq).toBe(9); // 3^2 = 9

    // C7: equip called with item and 'hand'
    expect(bot.equip).toHaveBeenCalledWith(craftingTableItem, 'hand');

    // C8: placeBlock called with the reference (dirt below) and face Vec3(0,1,0)
    const [refArg, faceArg] = bot.placeBlock.mock.calls[0];
    expect(refArg).toBe(dirtBlock);
    expect(faceArg.x).toBe(0);
    expect(faceArg.y).toBe(1);
    expect(faceArg.z).toBe(0);
  });

  // T2: Float inputs are rounded to nearest integer block
  it('T2: rounds float coords (10.7, 64.2, 20.5) to (11, 64, 21)', async () => {
    const bot = makeMockBot();
    const tx = 11, ty = 64, tz = 21; // expected after rounding

    const dirtBlock = { name: 'dirt' };
    bot.blockAt.mockImplementation(blockAtFromMap({
      [`${tx},${ty},${tz}`]:     { name: 'air' },
      [`${tx},${ty - 1},${tz}`]: dirtBlock,
    }));

    const dirtItem = { name: 'dirt', count: 1 };
    bot.inventory.items.mockReturnValue([dirtItem]);

    const result = await place_block({ block: 'dirt', x: 10.7, y: 64.2, z: 20.5 }, bot);

    // All blockAt calls must use rounded coords
    for (const call of bot.blockAt.mock.calls) {
      expect(Number.isInteger(call[0].x)).toBe(true);
      expect(Number.isInteger(call[0].y)).toBe(true);
      expect(Number.isInteger(call[0].z)).toBe(true);
    }

    // C10: returned position echoes rounded ints
    expect(result.position).toEqual({ x: 11, y: 64, z: 21 });
  });

  // T3: Target already occupied — equip and placeBlock must not be called
  it('T3: throws when target is occupied, equip and placeBlock not called', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockImplementation(blockAtFromMap({
      '10,64,20': { name: 'dirt' },
    }));

    await expect(
      place_block({ block: 'crafting_table', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: target already occupied by dirt/);

    expect(bot.equip).not.toHaveBeenCalled();
    expect(bot.placeBlock).not.toHaveBeenCalled();
  });

  // T4: All 6 neighbors return air/null — equip and placeBlock must not be called
  it('T4: throws no solid neighbor when all 6 neighbors are air or null', async () => {
    const bot = makeMockBot();
    // Target is air; all neighbors are also air (or null via default)
    bot.blockAt.mockImplementation(blockAtFromMap({
      '10,64,20': { name: 'air' },
      '9,64,20':  { name: 'air' },  // west
      '11,64,20': { name: 'air' },  // east
      '10,63,20': { name: 'air' },  // below
      '10,65,20': { name: 'air' },  // above
      '10,64,19': { name: 'air' },  // north
      '10,64,21': { name: 'air' },  // south
    }));

    await expect(
      place_block({ block: 'crafting_table', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: no solid neighbor at \{10,64,20\} to place against/);

    expect(bot.equip).not.toHaveBeenCalled();
    expect(bot.placeBlock).not.toHaveBeenCalled();
  });

  // T5: Block not in inventory — placeBlock must not be called
  it('T5: throws when block not in inventory, placeBlock not called', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockImplementation(blockAtFromMap({
      '10,64,20': { name: 'air' },
      '10,63,20': { name: 'dirt' },
    }));
    // inventory.items already returns [] from makeMockBot

    await expect(
      place_block({ block: 'crafting_table', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: crafting_table not in inventory/);

    expect(bot.placeBlock).not.toHaveBeenCalled();
  });

  // T6: pathfinder.goto rejection wraps as navigation failed
  it('T6: wraps pathfinder.goto rejection as navigation failed, equip and placeBlock not called', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockImplementation(blockAtFromMap({
      '10,64,20': { name: 'air' },
      '10,63,20': { name: 'dirt' },
    }));
    bot.pathfinder.goto.mockRejectedValue(new Error('NoPath'));

    await expect(
      place_block({ block: 'crafting_table', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: navigation failed: NoPath/);

    expect(bot.equip).not.toHaveBeenCalled();
    expect(bot.placeBlock).not.toHaveBeenCalled();
  });

  // T7: bot.equip rejection wraps as equip failed
  it('T7: wraps bot.equip rejection as equip failed, placeBlock not called', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockImplementation(blockAtFromMap({
      '10,64,20': { name: 'air' },
      '10,63,20': { name: 'dirt' },
    }));
    const dirtItem = { name: 'dirt', count: 1 };
    bot.inventory.items.mockReturnValue([dirtItem]);
    bot.equip.mockRejectedValue(new Error('busy'));

    await expect(
      place_block({ block: 'dirt', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: equip failed: busy/);

    expect(bot.placeBlock).not.toHaveBeenCalled();
  });

  // T8: bot.placeBlock rejection wraps as placeBlock failed
  it('T8: wraps bot.placeBlock rejection as placeBlock failed', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockImplementation(blockAtFromMap({
      '10,64,20': { name: 'air' },
      '10,63,20': { name: 'dirt' },
    }));
    const dirtItem = { name: 'dirt', count: 1 };
    bot.inventory.items.mockReturnValue([dirtItem]);
    bot.placeBlock.mockRejectedValue(new Error('blocked'));

    await expect(
      place_block({ block: 'dirt', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: placeBlock failed: blocked/);
  });

  // T9: Invalid coords / missing block key — bot.blockAt must NOT be called
  it('T9a: throws for missing block key, blockAt not called', async () => {
    const bot = makeMockBot();

    await expect(
      place_block({ x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: block must be a non-empty string/);

    expect(bot.blockAt).not.toHaveBeenCalled();
    expect(bot.equip).not.toHaveBeenCalled();
  });

  it('T9b: throws for empty string block, blockAt not called', async () => {
    const bot = makeMockBot();

    await expect(
      place_block({ block: '', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: block must be a non-empty string/);

    expect(bot.blockAt).not.toHaveBeenCalled();
  });

  it('T9c: throws for NaN x coord, blockAt not called', async () => {
    const bot = makeMockBot();

    await expect(
      place_block({ block: 'dirt', x: NaN, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: x, y, z must be finite numbers/);

    expect(bot.blockAt).not.toHaveBeenCalled();
    expect(bot.equip).not.toHaveBeenCalled();
  });

  it('T9d: throws for Infinity z coord, blockAt not called', async () => {
    const bot = makeMockBot();

    await expect(
      place_block({ block: 'dirt', x: 10, y: 64, z: Infinity }, bot)
    ).rejects.toThrow(/place_block: x, y, z must be finite numbers/);

    expect(bot.blockAt).not.toHaveBeenCalled();
    expect(bot.equip).not.toHaveBeenCalled();
  });

  // T10: Unknown block name — bot.blockAt must NOT be called
  it('T10: throws for unknown block name, blockAt not called', async () => {
    const bot = makeMockBot();

    await expect(
      place_block({ block: 'obsidiumX', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: unknown block "obsidiumX"/);

    expect(bot.blockAt).not.toHaveBeenCalled();
    expect(bot.equip).not.toHaveBeenCalled();
  });

  // T11: bot null / pathfinder missing
  it('T11a: throws when bot is null', async () => {
    await expect(
      place_block({ block: 'dirt', x: 10, y: 64, z: 20 }, null)
    ).rejects.toThrow(/place_block: bot not connected/);
  });

  it('T11b: throws when bot.pathfinder is not loaded', async () => {
    const bot = makeMockBot();
    delete bot.pathfinder;

    await expect(
      place_block({ block: 'dirt', x: 10, y: 64, z: 20 }, bot)
    ).rejects.toThrow(/place_block: pathfinder plugin not loaded/);
  });
});
