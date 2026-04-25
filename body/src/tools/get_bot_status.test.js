const get_bot_status = require('./get_bot_status');

describe('get_bot_status tool', () => {
  const makePos = (distance) => ({ distanceTo: jest.fn().mockReturnValue(distance) });

  const makeBot = ({
    health = 20,
    food = 20,
    posXYZ = [0, 64, 0],
    inventoryItems = [],
    entities = {},
  } = {}) => {
    const botEntity = {
      position: {
        x: posXYZ[0],
        y: posXYZ[1],
        z: posXYZ[2],
        distanceTo: jest.fn().mockReturnValue(0),
      },
    };
    const bot = {
      health,
      food,
      entity: botEntity,
      inventory: { items: () => inventoryItems },
      entities: { self: botEntity, ...entities },
    };
    return bot;
  };

  it('T1: happy path — full shape with rounding', async () => {
    const nearbyEntity = {
      username: 'Steve',
      type: 'player',
      position: makePos(5.27),
    };
    const bot = makeBot({
      health: 18,
      food: 15,
      posXYZ: [1.234, 64.5, -7.89],
      inventoryItems: [
        { name: 'oak_log', count: 3 },
        { name: 'cobblestone', count: 12 },
      ],
      entities: { steve: nearbyEntity },
    });

    const result = await get_bot_status({}, bot);

    expect(result).toEqual({
      health: 18,
      food: 15,
      position: { x: 1.2, y: 64.5, z: -7.9 },
      inventory: [
        { name: 'oak_log', count: 3 },
        { name: 'cobblestone', count: 12 },
      ],
      nearby_entities: [
        { name: 'Steve', type: 'player', distance: 5.3 },
      ],
    });
  });

  it('T2: throws when bot is null', async () => {
    await expect(get_bot_status({}, null)).rejects.toThrow(/bot not connected/);
  });

  it('T3: throws when bot has no entity yet', async () => {
    const bot = makeBot();
    delete bot.entity;
    await expect(get_bot_status({}, bot)).rejects.toThrow(/no entity yet/);
  });

  it('T4: empty inventory returns []', async () => {
    const bot = makeBot({ inventoryItems: [] });
    const result = await get_bot_status({}, bot);
    expect(result.inventory).toEqual([]);
  });

  it('T5: no nearby entities when bot.entities contains only bot.entity', async () => {
    const bot = makeBot({ entities: {} });
    // bot.entities only has 'self' which IS bot.entity — excluded by identity
    const result = await get_bot_status({}, bot);
    expect(result.nearby_entities).toEqual([]);
  });

  it('T6: filters out bot.entity by identity and far entities by distance', async () => {
    const far = { username: 'Far', type: 'player', position: makePos(20) };
    const near = { username: 'Near', type: 'player', position: makePos(10) };
    const bot = makeBot({
      entities: { far, near },
    });
    // bot.entities: { self: bot.entity, far, near }
    const result = await get_bot_status({}, bot);
    expect(result.nearby_entities).toHaveLength(1);
    expect(result.nearby_entities[0].distance).toBe(10);
  });

  it('T7: name fallback chain — username > displayName > name > "unknown"', async () => {
    const a = { username: 'Steve', type: 'player', position: makePos(5) };
    const b = { displayName: 'Zombie', type: 'mob', position: makePos(5) };
    const c = { name: 'cow', type: 'mob', position: makePos(5) };
    const d = { type: 'object', position: makePos(5) };
    const bot = makeBot({
      entities: { a, b, c, d },
    });

    const result = await get_bot_status({}, bot);
    const names = result.nearby_entities.map((e) => e.name);
    expect(names).toContain('Steve');
    expect(names).toContain('Zombie');
    expect(names).toContain('cow');
    expect(names).toContain('unknown');
  });
});
