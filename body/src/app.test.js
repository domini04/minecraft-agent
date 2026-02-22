const request = require('supertest');
const app = require('./app');

describe('GET /status', () => {
  it('returns 200 with ok: true', async () => {
    const response = await request(app)
      .get('/status')
      .expect('Content-Type', /json/)
      .expect(200);

    expect(response.body).toEqual({ ok: true });
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
