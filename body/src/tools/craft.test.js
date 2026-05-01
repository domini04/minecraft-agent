const craft = require('./craft');
const { goals } = require('mineflayer-pathfinder');

describe('craft tool', () => {
  const makeMockBot = () => ({
    registry: {
      itemsByName: {
        stick: { id: 280, name: 'stick' },
        wooden_pickaxe: { id: 274, name: 'wooden_pickaxe' },
        crafting_table: { id: 58, name: 'crafting_table' },
        oak_planks: { id: 5, name: 'oak_planks' },
      },
    },
    recipesFor: jest.fn(),
    recipesAll: jest.fn(),
    craft: jest.fn().mockResolvedValue(undefined),
    blockAt: jest.fn(),
    pathfinder: { goto: jest.fn().mockResolvedValue(undefined) },
    inventory: { items: jest.fn().mockReturnValue([]) },
    entity: { position: { x: 0, y: 64, z: 0 } },
  });

  // Recipe is opaque — tests don't introspect its shape.
  const fakeRecipe = (resultId = 280, resultCount = 4) => ({
    result: { id: resultId, count: resultCount },
    ingredients: [],
  });

  // T1: 2x2 (inventory) happy path — stick crafted without table
  it('T1: crafts stick from inventory (2x2), returns correct shape', async () => {
    const bot = makeMockBot();
    const recipe = fakeRecipe(280, 4);
    bot.recipesFor.mockReturnValue([recipe]);
    bot.inventory.items.mockReturnValue([{ name: 'stick', count: 4 }]);

    const result = await craft({ item: 'stick', count: 4 }, bot);

    // recipesFor called with null table (2x2 path)
    expect(bot.recipesFor.mock.calls[0][3]).toBeNull();
    // bot.craft called with null table
    expect(bot.craft.mock.calls[0][2]).toBeNull();
    // pathfinder NOT called
    expect(bot.pathfinder.goto).not.toHaveBeenCalled();
    // correct return shape
    expect(result).toEqual({ crafted: 4, item: 'stick', final_count: 4 });
  });

  // T2: 3x3 (crafting table) happy path
  it('T2: crafts wooden_pickaxe using crafting table, GoalNear called with range 2', async () => {
    const bot = makeMockBot();
    const tableBlock = { name: 'crafting_table' };
    bot.blockAt.mockReturnValue(tableBlock);
    const recipe = fakeRecipe(274, 1);
    bot.recipesFor.mockReturnValue([recipe]);
    bot.inventory.items.mockReturnValue([{ name: 'wooden_pickaxe', count: 1 }]);

    const result = await craft(
      { item: 'wooden_pickaxe', count: 1, crafting_table_pos: { x: 10, y: 64, z: 5 } },
      bot
    );

    // pathfinder.goto called once
    expect(bot.pathfinder.goto).toHaveBeenCalledTimes(1);
    const goalArg = bot.pathfinder.goto.mock.calls[0][0];
    // GoalNear instance with correct coords and range 2
    expect(goalArg).toBeInstanceOf(goals.GoalNear);
    expect(goalArg.x).toBe(10);
    expect(goalArg.y).toBe(64);
    expect(goalArg.z).toBe(5);
    expect(goalArg.rangeSq).toBe(4); // GoalNear stores range squared: 2^2 = 4
    // bot.craft called with the tableBlock
    expect(bot.craft.mock.calls[0][2]).toBe(tableBlock);
    // correct return shape
    expect(result).toEqual({ crafted: 1, item: 'wooden_pickaxe', final_count: 1 });
  });

  // T3: 3x3 recipe exists but crafting_table_pos absent — directive error
  it('T3: throws directive when 3x3 recipe exists but no crafting_table_pos provided', async () => {
    const bot = makeMockBot();
    bot.recipesFor.mockReturnValue([]); // no 2x2 recipe satisfiable
    bot.recipesAll
      .mockReturnValueOnce([])         // allInv: no 2x2 recipe exists at all
      .mockReturnValueOnce([fakeRecipe()]); // allTable: table recipe exists

    await expect(craft({ item: 'wooden_pickaxe', count: 1 }, bot)).rejects.toThrow(
      /craft: wooden_pickaxe requires a crafting_table; pass crafting_table_pos or place a table first via place_block/
    );
  });

  // T4: Insufficient materials — recipe exists in context but inventory short
  it('T4: throws insufficient materials when recipe exists but inventory short', async () => {
    const bot = makeMockBot();
    bot.recipesFor.mockReturnValue([]); // can't satisfy with current inventory
    bot.recipesAll
      .mockReturnValueOnce([fakeRecipe()]) // allInv: 2x2 recipe exists
      .mockReturnValueOnce([fakeRecipe()]); // allTable: recipe exists

    await expect(craft({ item: 'stick', count: 64 }, bot)).rejects.toThrow(
      /craft: insufficient materials for stick x64/
    );
  });

  // T5: Unknown item name — recipesFor never called
  it('T5: throws for unknown item name, recipesFor never called', async () => {
    const bot = makeMockBot();

    await expect(craft({ item: 'unobtanium', count: 1 }, bot)).rejects.toThrow(
      /craft: unknown item name "unobtanium"/
    );
    expect(bot.recipesFor).not.toHaveBeenCalled();
  });

  // T6: Param validation (item, count, crafting_table_pos)
  it('T6a: throws when item is missing', async () => {
    const bot = makeMockBot();
    await expect(craft({ count: 1 }, bot)).rejects.toThrow(
      /craft: item must be a non-empty string/
    );
  });

  it('T6b: throws when item is empty string', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: '', count: 1 }, bot)).rejects.toThrow(
      /craft: item must be a non-empty string/
    );
  });

  it('T6c: throws when item is a number', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: 42, count: 1 }, bot)).rejects.toThrow(
      /craft: item must be a non-empty string/
    );
  });

  it('T6d: throws when count is 0', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: 'stick', count: 0 }, bot)).rejects.toThrow(
      /craft: count must be a positive integer/
    );
  });

  it('T6e: throws when count is -1', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: 'stick', count: -1 }, bot)).rejects.toThrow(
      /craft: count must be a positive integer/
    );
  });

  it('T6f: throws when count is 1.5 (float)', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: 'stick', count: 1.5 }, bot)).rejects.toThrow(
      /craft: count must be a positive integer/
    );
  });

  it('T6g: throws when count is a string', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: 'stick', count: 'abc' }, bot)).rejects.toThrow(
      /craft: count must be a positive integer/
    );
  });

  it('T6h: throws when count is NaN', async () => {
    const bot = makeMockBot();
    await expect(craft({ item: 'stick', count: NaN }, bot)).rejects.toThrow(
      /craft: count must be a positive integer/
    );
  });

  it('T6i: throws when crafting_table_pos has missing field (no z)', async () => {
    const bot = makeMockBot();
    await expect(
      craft({ item: 'stick', count: 1, crafting_table_pos: { x: 1, y: 2 } }, bot)
    ).rejects.toThrow(/craft: crafting_table_pos must be \{x, y, z\} integers/);
  });

  it('T6j: throws when crafting_table_pos has non-integer field (float)', async () => {
    const bot = makeMockBot();
    await expect(
      craft({ item: 'stick', count: 1, crafting_table_pos: { x: 1.5, y: 2, z: 3 } }, bot)
    ).rejects.toThrow(/craft: crafting_table_pos must be \{x, y, z\} integers/);
  });

  it('T6k: throws when crafting_table_pos has string field', async () => {
    const bot = makeMockBot();
    await expect(
      craft({ item: 'stick', count: 1, crafting_table_pos: { x: 'a', y: 2, z: 3 } }, bot)
    ).rejects.toThrow(/craft: crafting_table_pos must be \{x, y, z\} integers/);
  });

  // T7: crafting_table_pos provided but blockAt returns wrong block (dirt)
  it('T7: throws when blockAt returns wrong block name (dirt), bot.craft not called', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockReturnValue({ name: 'dirt' });

    await expect(
      craft({ item: 'wooden_pickaxe', count: 1, crafting_table_pos: { x: 5, y: 64, z: 5 } }, bot)
    ).rejects.toThrow(/craft: no crafting_table at position \{5,64,5\} \(found dirt\)/);
    expect(bot.craft).not.toHaveBeenCalled();
  });

  // T8: crafting_table_pos provided but blockAt returns null
  it('T8: throws when blockAt returns null, bot.craft not called', async () => {
    const bot = makeMockBot();
    bot.blockAt.mockReturnValue(null);

    await expect(
      craft({ item: 'wooden_pickaxe', count: 1, crafting_table_pos: { x: 5, y: 64, z: 5 } }, bot)
    ).rejects.toThrow(/craft: no crafting_table at position \{5,64,5\} \(found null\)/);
    expect(bot.craft).not.toHaveBeenCalled();
  });

  // T9: pathfinder.goto rejection wraps as navigation failed
  it('T9: wraps pathfinder.goto rejection as navigation to table failed, bot.craft not called', async () => {
    const bot = makeMockBot();
    bot.pathfinder.goto.mockRejectedValue(new Error('path blocked'));

    await expect(
      craft({ item: 'wooden_pickaxe', count: 1, crafting_table_pos: { x: 5, y: 64, z: 5 } }, bot)
    ).rejects.toThrow(/craft: navigation to table failed: path blocked/);
    expect(bot.craft).not.toHaveBeenCalled();
  });

  // T10: bot.craft rejection wraps as bot.craft failed
  it('T10: wraps bot.craft rejection as bot.craft failed', async () => {
    const bot = makeMockBot();
    const recipe = fakeRecipe(280, 4);
    bot.recipesFor.mockReturnValue([recipe]);
    bot.craft.mockRejectedValue(new Error('output slot full'));

    await expect(craft({ item: 'stick', count: 4 }, bot)).rejects.toThrow(
      /craft: bot\.craft failed: output slot full/
    );
  });

  // T11: bot null
  it('T11: throws when bot is null', async () => {
    await expect(craft({ item: 'stick', count: 1 }, null)).rejects.toThrow(
      /craft: bot not connected/
    );
  });

  // T12: pathfinder plugin guards
  it('T12a: throws when pathfinder missing AND crafting_table_pos provided', async () => {
    const bot = makeMockBot();
    delete bot.pathfinder;

    await expect(
      craft({ item: 'wooden_pickaxe', count: 1, crafting_table_pos: { x: 5, y: 64, z: 5 } }, bot)
    ).rejects.toThrow(/craft: pathfinder plugin not loaded/);
  });

  it('T12b: pathfinder missing but no crafting_table_pos — proceeds to inventory craft', async () => {
    const bot = makeMockBot();
    delete bot.pathfinder;
    const recipe = fakeRecipe(280, 4);
    bot.recipesFor.mockReturnValue([recipe]);
    bot.inventory.items.mockReturnValue([{ name: 'stick', count: 4 }]);

    // Should NOT throw on pathfinder grounds; succeeds as 2x2 craft
    const result = await craft({ item: 'stick', count: 4 }, bot);
    expect(result).toEqual({ crafted: 4, item: 'stick', final_count: 4 });
  });

  // Additional: no recipe known at all
  it('extra: throws no recipe known when recipesAll returns empty everywhere', async () => {
    const bot = makeMockBot();
    bot.recipesFor.mockReturnValue([]);
    bot.recipesAll.mockReturnValue([]);

    await expect(craft({ item: 'stick', count: 1 }, bot)).rejects.toThrow(
      /craft: no recipe known for "stick"/
    );
  });

  // Additional: insufficient materials with table provided (3x3 context)
  it('extra: throws insufficient materials for table recipe when materials short', async () => {
    const bot = makeMockBot();
    const tableBlock = { name: 'crafting_table' };
    bot.blockAt.mockReturnValue(tableBlock);
    bot.recipesFor.mockReturnValue([]); // can't satisfy
    bot.recipesAll
      .mockReturnValueOnce([fakeRecipe()]) // allInv: 2x2 recipe exists
      .mockReturnValueOnce([fakeRecipe()]); // allTable: exists too

    await expect(
      craft({ item: 'wooden_pickaxe', count: 1, crafting_table_pos: { x: 5, y: 64, z: 5 } }, bot)
    ).rejects.toThrow(/craft: insufficient materials for wooden_pickaxe x1/);
  });
});
