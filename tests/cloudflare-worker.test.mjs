import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../deploy/worker.mjs';

function snapshot() {
  return { schemaVersion: 1, game: '리니지 클래식', intervalSeconds: 600,
    generatedAt: '2026-10-14T00:00:00Z', nextUpdateAt: '2026-10-14T00:10:00Z',
    lastSuccessfulUpdateAt: '2026-10-14T00:00:00Z',
    sources: [{ id: 'itembay', name: '아이템베이', status: 'ok', updatedAt: '2026-10-14T00:00:00Z', sampleCount: 1, completedCount: 1 }],
    servers: [], coverage: { mode: 'sample' },
    listings: [{ id: 'itembay:123', source: 'itembay', server: '아덴', kind: 'completed',
      unitPrice: 65000, priceKRW: 65000, quantity: 1000000, observedAt: '2026-10-14T00:00:00Z',
      url: 'https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=123', title: 'raw subject', vcMemberID: 'must-not-be-stored' }] };
}
function environment(initial = null) {
  const values = new Map(initial ? [['snapshot', initial]] : []);
  return { values, MARKET_UPLOAD_TOKEN: 'test-secret',
    MARKET: { get: async k => values.get(k), put: async (k, v) => values.set(k, v) },
    ASSETS: { fetch: async () => new Response('Not found', { status: 404 }) } };
}
function upload(data, token = 'test-secret') {
  return new Request('https://example.workers.dev/internal/snapshot', { method: 'POST',
    headers: { Authorization: 'Bearer ' + token }, body: JSON.stringify(data) });
}

test('unauthorized uploads leave the last good snapshot untouched', async () => {
  const env = environment('previous');
  assert.equal((await worker.fetch(upload(snapshot(), 'wrong'), env)).status, 401);
  assert.equal(env.values.get('snapshot'), 'previous');
});
test('valid upload removes seller fields and source subjects', async () => {
  const env = environment();
  assert.equal((await worker.fetch(upload(snapshot()), env)).status, 200);
  const stored = env.values.get('snapshot');
  assert.ok(!stored.includes('must-not-be-stored'));
  assert.ok(!stored.includes('raw subject'));
  assert.equal(JSON.parse(stored).listings[0].unitPrice, 65000);
});
test('invalid prices and external source URLs are rejected without replacing data', async () => {
  for (const patch of [{ quantity: 0 }, { unitPrice: null }, { url: 'https://attacker.example/' }]) {
    const env = environment('previous'), data = snapshot(); Object.assign(data.listings[0], patch);
    assert.equal((await worker.fetch(upload(data), env)).status, 400);
    assert.equal(env.values.get('snapshot'), 'previous');
  }
});
test('cached API supports ETag conditional requests and HEAD', async () => {
  const env = environment(JSON.stringify(snapshot()));
  const url = 'https://example.workers.dev/api/prices';
  const response = await worker.fetch(new Request(url), env);
  assert.equal(response.status, 200); assert.equal((await response.json()).listings.length, 1);
  const etag = response.headers.get('ETag'); assert.ok(etag);
  assert.equal((await worker.fetch(new Request(url, { headers: { 'If-None-Match': etag } }), env)).status, 304);
  assert.equal(await (await worker.fetch(new Request(url, { method: 'HEAD' }), env)).text(), '');
});
test('missing snapshots fail visibly and unknown mutation routes do not write', async () => {
  const env = environment();
  assert.equal((await worker.fetch(new Request('https://example.workers.dev/api/prices'), env)).status, 503);
  assert.equal((await worker.fetch(new Request('https://example.workers.dev/internal/other', { method: 'POST' }), env)).status, 404);
  assert.equal(env.values.size, 0);
});
test('a packaged actual snapshot can bootstrap an empty account', async () => {
  const env = environment(); env.ASSETS.fetch = async () => new Response(JSON.stringify(snapshot()));
  const response = await worker.fetch(new Request('https://example.workers.dev/api/prices'), env);
  assert.equal(response.status, 200); assert.equal((await response.json()).listings[0].quantity, 1000000);
});
