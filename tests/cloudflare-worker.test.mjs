import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import worker from '../deploy/worker.mjs';

const officialGuideTitles = ['방어구', '장신구', '무기', '레벨 퀘스트', '던전',
  '몽환의 섬', '요정 마법', '기사 마법', '아이템 소개', '필드 사냥터'];

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

function itemListing(overrides = {}) {
  return { id: 'barotem:401', source: 'barotem', server: '아덴', kind: 'ask',
    itemId: 'lc-sword', itemName: '장검', enchant: 6, blessing: 'normal',
    priceKRW: 12000, quantity: 2, unitPrice: 6000,
    observedAt: '2026-10-14T00:00:00Z',
    url: 'https://www.barotem.com/product/view/401', title: '장검', ...overrides };
}

function itemSnapshot() {
  return { intervalSeconds: 3600, generatedAt: '2026-10-14T00:00:00Z',
    nextUpdateAt: '2026-10-14T01:00:00Z', lastSuccessfulUpdateAt: '2026-10-14T00:00:00Z', stale: false,
    sources: ['barotem', 'itembay'].map(id => ({ id, name: id, status: 'ok',
      updatedAt: '2026-10-14T00:00:00Z', sampleCount: 99, completedCount: 99 })),
    listings: [itemListing(), itemListing({ id: 'itembay:501', source: 'itembay',
      priceKRW: 6500, quantity: 1, unitPrice: 6500,
      url: 'https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=501' }),
    itemListing({ id: 'itembay:502', source: 'itembay', kind: 'completed',
      priceKRW: 6300, quantity: 1, unitPrice: 6300,
      url: 'https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=502' })],
    groups: [], coverage: { mode: 'sample', pagesPerSource: 3, maxRows: 372 },
    catalog: { mappingVersion: 'v1', verifiedAt: null, sources: [], entries: [
      { id: 'lc-sword', name: '장검', aliases: ['장검'], category: 'weapon',
        officialVerified: false, officialSource: null, referenceUrl: null },
    ] } };
}

function snapshotWithItems() {
  return { ...snapshot(), items: itemSnapshot() };
}

async function storedSnapshot(data) {
  const env = environment();
  assert.equal((await worker.fetch(upload(data), env)).status, 200);
  return JSON.parse(env.values.get('snapshot'));
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

test('currency-only schema version 1 uploads remain compatible without item data', async () => {
  const stored = await storedSnapshot(snapshot());
  assert.equal(stored.schemaVersion, 1);
  assert.equal(stored.intervalSeconds, 600);
  assert.equal(stored.units, 'KRW_PER_1M_ADENA');
  assert.equal(Object.hasOwn(stored, 'items'), false);
});

test('optional item data keeps per-item units and its independent hourly schedule', async () => {
  const stored = await storedSnapshot(snapshotWithItems());
  assert.equal(stored.intervalSeconds, 600);
  assert.equal(stored.items.intervalSeconds, 3600);
  assert.equal(stored.items.nextUpdateAt, '2026-10-14T01:00:00Z');
  assert.equal(stored.items.listings.length, 3);
  assert.equal(stored.items.listings[0].unitPrice, 6000);
  assert.equal(stored.items.listings[0].priceKRW / stored.items.listings[0].quantity, 6000);
  assert.equal(stored.items.catalog.entries[0].id, 'lc-sword');
  assert.equal(stored.items.catalog.mappingVersion, 'v1');
});

test('nested item and currency metadata discard seller details and canonicalize public links', async () => {
  const data = snapshotWithItems();
  data.seller = 'PRIVATE-ROOT';
  data.listings[0].url += '&phone=PRIVATE-CURRENCY-CONTACT#PRIVATE-FRAGMENT';
  data.sources[0].name = 'PRIVATE-CURRENCY-SOURCE';
  data.sources[0].sourceUrl = 'https://attacker.example/PRIVATE-SOURCE';
  data.servers = [{ name: '아덴', seller: 'PRIVATE-SERVER', historyKind: 'completed',
    history: [{ at: data.generatedAt, value: 65000, kind: 'completed', seller: 'PRIVATE-HISTORY' }] }];
  data.coverage = { message: 'PRIVATE-CURRENCY-COVERAGE', contact: 'PRIVATE-CONTACT' };
  data.items.seller = 'PRIVATE-ITEM-ROOT';
  data.items.listings[0].seller = 'PRIVATE-SELLER';
  data.items.listings[0].phone = 'PRIVATE-PHONE';
  data.items.listings[0].title = 'PRIVATE-RAW-SUBJECT';
  data.items.listings[0].url += '?phone=PRIVATE-ITEM-CONTACT#PRIVATE-FRAGMENT';
  data.items.sources[0].name = 'PRIVATE-ITEM-SOURCE';
  data.items.sources[0].sourceUrl = 'https://attacker.example/PRIVATE-SOURCE';
  data.items.sources[0].warnings = ['PRIVATE-WARNING'];
  data.items.sources[0].error = 'PRIVATE-ERROR';
  data.items.groups = [{ id: 'PRIVATE-FORGED-GROUP', seller: 'PRIVATE-GROUP', askMedian: 1 }];
  data.items.coverage.message = 'PRIVATE-ITEM-COVERAGE';
  data.items.catalog.seller = 'PRIVATE-CATALOG';
  data.items.catalog.entries[0].seller = 'PRIVATE-CATALOG-SELLER';
  data.items.catalog.entries[0].description = 'PRIVATE-CATALOG-DESCRIPTION';
  data.items.catalog.entries[0].referenceUrl = 'https://attacker.example/PRIVATE-REFERENCE';
  data.items.catalog.sources = [{ url: 'https://attacker.example/PRIVATE-REFERENCE', name: 'PRIVATE-NAME' }];
  const stored = await storedSnapshot(data);
  assert.ok(!JSON.stringify(stored).includes('PRIVATE-'));
  assert.equal(stored.items.listings[0].title, '장검');
  assert.equal(stored.items.listings[0].url, 'https://www.barotem.com/product/view/401');
  assert.equal(stored.listings[0].url, 'https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=123');
  assert.equal(stored.items.catalog.entries[0].referenceUrl, null);
  assert.deepEqual(stored.items.catalog.sources, []);
});

test('item groups and source medians are rebuilt from deduplicated ask and completed rows', async () => {
  const data = snapshotWithItems();
  data.items.listings.push(structuredClone(data.items.listings[1]));
  data.items.groups = [{ id: 'forged', itemId: 'lc-sword', server: '아덴', enchant: 6,
    blessing: 'normal', count: 999, askMedian: 1, sourceStats: [{ id: 'barotem', askMedian: 1 }] }];
  const stored = await storedSnapshot(data), items = stored.items;
  assert.equal(items.listings.length, 3);
  assert.equal(items.groups.length, 1);
  const group = items.groups[0];
  assert.notEqual(group.id, 'forged');
  assert.equal(group.count, 3);
  assert.equal(group.listingCount, 2);
  assert.equal(group.completedCount, 1);
  assert.equal(group.askMedian, 6250);
  assert.equal(group.completedMedian, 6300);
  assert.equal(group.minAsk, 6000);
  assert.equal(group.maxAsk, 6500);
  const barotem = group.sourceStats.find(source => source.id === 'barotem');
  const itembay = group.sourceStats.find(source => source.id === 'itembay');
  assert.equal(barotem.askMedian, 6000);
  assert.equal(barotem.completedMedian, null);
  assert.equal(itembay.askMedian, 6500);
  assert.equal(itembay.completedMedian, 6300);
  assert.equal(items.sources.find(source => source.id === 'barotem').sampleCount, 1);
  assert.equal(items.sources.find(source => source.id === 'itembay').sampleCount, 2);
});

test('same public listing identifier remains distinct for ask and completed observations', async () => {
  const data = snapshotWithItems();
  data.items.listings[2].id = data.items.listings[1].id;
  data.items.listings[2].url = data.items.listings[1].url;
  const stored = await storedSnapshot(data);
  assert.equal(stored.items.listings.length, 3);
  assert.equal(stored.items.groups[0].completedCount, 1);
  assert.equal(stored.items.groups[0].listingCount, 2);
});

test('unknown enchant, zero enchant, blessings, and servers form separate comparison groups', async () => {
  const data = snapshotWithItems();
  const variants = [{ enchant: null }, { enchant: 0 }, { blessing: 'unknown' },
    { blessing: 'blessed' }, { blessing: 'cursed' }, { server: '데포로쥬' }];
  for (const [index, variant] of variants.entries()) {
    data.items.listings.push(itemListing({ id: 'barotem:' + (410 + index), ...variant }));
  }
  const stored = await storedSnapshot(data), groups = stored.items.groups;
  assert.equal(groups.length, 7);
  const keys = groups.map(group => JSON.stringify([group.itemId, group.server, group.enchant, group.blessing]));
  assert.equal(new Set(keys).size, 7);
  assert.ok(groups.some(group => group.enchant === null && group.blessing === 'normal'));
  assert.ok(groups.some(group => group.enchant === 0 && group.blessing === 'normal'));
  assert.ok(groups.some(group => group.enchant === 6 && group.blessing === 'unknown'));
  assert.equal(groups.find(group => group.server === '데포로쥬').count, 1);
});

test('malformed item fields reject the upload without replacing the previous snapshot', async () => {
  const patches = [
    { itemId: 'lc-unknown' }, { itemName: '다른 이름' }, { id: 'PRIVATE-SELLER' },
    { id: 'itembay:401' }, { source: 'unknown' }, { kind: 'sold' },
    { quantity: 0 }, { quantity: -1 }, { quantity: 1.5 }, { quantity: true }, { quantity: '2' },
    { quantity: Number.MAX_SAFE_INTEGER + 1 }, { priceKRW: 0 }, { priceKRW: null },
    { unitPrice: 1 }, { unitPrice: null }, { unitPrice: '6000' },
    { enchant: 1.5 }, { enchant: true }, { enchant: '6' }, { enchant: 101 }, { enchant: -101 },
    { blessing: 'unrecognized' }, { blessing: null }, { server: '연락처 010-1234-5678' },
    { observedAt: 'not-a-time' }, { observedAt: null }, { observedAt: '2026-10-14T00:00:00' },
    { url: 'https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=401' },
    { url: 'https://attacker.example/' }, { url: 'http://www.barotem.com/product/view/401' },
  ];
  for (const patch of patches) {
    const data = snapshotWithItems(), env = environment('previous');
    Object.assign(data.items.listings[0], patch);
    assert.equal((await worker.fetch(upload(data), env)).status, 400, JSON.stringify(patch));
    assert.equal(env.values.get('snapshot'), 'previous');
  }
});

test('malformed item catalog, schedule, and source metadata preserve the last public snapshot', async () => {
  const mutations = [
    data => { data.items = null; },
    data => { data.items.intervalSeconds = 600; },
    data => { data.items.generatedAt = null; },
    data => { data.items.nextUpdateAt = 'not-a-time'; },
    data => { data.items.lastSuccessfulUpdateAt = 'not-a-time'; },
    data => { data.items.catalog.entries = []; },
    data => { data.items.catalog.entries.push(structuredClone(data.items.catalog.entries[0])); },
    data => { data.items.catalog.entries[0].id = 'unprefixed'; },
    data => { data.items.catalog.entries[0].name = 'contact@example.com'; },
    data => { data.items.catalog.verifiedAt = 'not-a-time'; },
    data => { data.items.sources[0].updatedAt = 'not-a-time'; },
    data => { data.items.sources[0].updatedAt = null; },
    data => { data.items.sources[0].status = 'pending'; },
    data => { data.items.sources[0].status = 'invented'; },
    data => { data.items.sources.push(structuredClone(data.items.sources[0])); },
    data => { data.items.sources = []; },
  ];
  for (const [index, mutate] of mutations.entries()) {
    const data = snapshotWithItems(), env = environment('previous');
    mutate(data);
    assert.equal((await worker.fetch(upload(data), env)).status, 400, 'mutation ' + index);
    assert.equal(env.values.get('snapshot'), 'previous');
  }
});

test('failed item sources retain the original successful observation timestamp', async () => {
  const data = snapshotWithItems(), original = '2026-10-13T23:00:00Z';
  data.items.sources[0].status = 'error';
  data.items.sources[0].updatedAt = original;
  data.items.sources[0].error = 'PRIVATE-UPSTREAM-ERROR';
  data.items.listings[0].observedAt = original;
  data.items.lastSuccessfulUpdateAt = original;
  const stored = await storedSnapshot(data), source = stored.items.sources[0];
  assert.equal(source.status, 'error');
  assert.equal(source.updatedAt, original);
  assert.equal(stored.items.lastSuccessfulUpdateAt, original);
  assert.equal(stored.items.stale, true);
  assert.equal(stored.items.listings[0].unitPrice, 6000);
  assert.equal(stored.items.groups[0].sourceStats.find(value => value.id === 'barotem').updatedAt, original);
  assert.ok(!JSON.stringify(stored).includes('PRIVATE-'));
});

test('verified official NC references are retained with canonical metadata', async () => {
  for (const url of ['https://lineageclassic.plaync.com/ko-kr/gameguide',
    'https://about.ncsoft.com/news/article/lineage-classic']) {
    const data = snapshotWithItems(), entry = data.items.catalog.entries[0];
    entry.officialVerified = true;
    entry.referenceUrl = url;
    entry.officialSource = { url, title: 'PRIVATE-SOURCE-TITLE', verifiedAt: data.generatedAt, seller: 'PRIVATE-SELLER' };
    data.items.catalog.sources = [{ url, name: 'PRIVATE-SOURCE-NAME' }];
    const stored = await storedSnapshot(data), safe = stored.items.catalog.entries[0];
    assert.equal(safe.officialVerified, true);
    assert.equal(safe.referenceUrl, url);
    assert.equal(safe.officialSource.url, url);
    assert.equal(safe.officialSource.verifiedAt, data.generatedAt);
    assert.ok(!JSON.stringify(stored).includes('PRIVATE-'));
  }
});

test('unofficial or credential-bearing, queried, and external catalog URLs are removed', async () => {
  const urls = ['https://attacker.example/item', 'http://lineageclassic.plaync.com/ko-kr/gameguide',
    'https://user:password@lineageclassic.plaync.com/ko-kr/gameguide',
    'https://lineageclassic.plaync.com.evil.example/ko-kr/gameguide',
    'https://lineageclassic.plaync.com/other/item',
    'https://lineageclassic.plaync.com/ko-kr/gameguide?phone=PRIVATE-CONTACT',
    'https://lineageclassic.plaync.com/ko-kr/gameguide#PRIVATE-FRAGMENT'];
  for (const url of urls) {
    const data = snapshotWithItems(), entry = data.items.catalog.entries[0];
    entry.officialVerified = true;
    entry.referenceUrl = url;
    entry.officialSource = { url, verifiedAt: data.generatedAt };
    const stored = await storedSnapshot(data), safe = stored.items.catalog.entries[0];
    assert.equal(safe.officialVerified, false, url);
    assert.equal(safe.referenceUrl, null, url);
    assert.equal(safe.officialSource, null, url);
  }
  const data = snapshotWithItems();
  data.items.catalog.entries[0].referenceUrl = 'https://lineageclassic.plaync.com/ko-kr/gameguide';
  assert.equal((await storedSnapshot(data)).items.catalog.entries[0].referenceUrl, null);
});

test('API bootstrap validates item data and strips private fields before public delivery', async () => {
  const env = environment(), data = snapshotWithItems();
  data.items.listings[0].seller = 'PRIVATE-SELLER';
  data.items.listings[0].title = 'PRIVATE-RAW-SUBJECT';
  data.items.groups = [{ id: 'PRIVATE-FORGED-GROUP', askMedian: 1 }];
  env.ASSETS.fetch = async () => new Response(JSON.stringify(data));
  const response = await worker.fetch(new Request('https://example.workers.dev/api/prices'), env);
  assert.equal(response.status, 200);
  const text = await response.text(), delivered = JSON.parse(text);
  assert.ok(!text.includes('PRIVATE-'));
  assert.equal(delivered.items.listings.length, 3);
  assert.equal(delivered.items.groups[0].askMedian, 6250);
  data.items.listings[0].unitPrice = 1;
  assert.equal((await worker.fetch(new Request('https://example.workers.dev/api/prices'), env)).status, 503);
});

test('item price changes alter API ETags while currency values remain identical', async () => {
  const data = snapshotWithItems(), env = environment();
  assert.equal((await worker.fetch(upload(data), env)).status, 200);
  const url = 'https://example.workers.dev/api/prices';
  const first = await worker.fetch(new Request(url), env), firstEtag = first.headers.get('ETag');
  const firstPayload = await first.json();
  data.items.listings[0].priceKRW = 14000;
  data.items.listings[0].unitPrice = 7000;
  assert.equal((await worker.fetch(upload(data), env)).status, 200);
  const second = await worker.fetch(new Request(url, { headers: { 'If-None-Match': firstEtag } }), env);
  assert.equal(second.status, 200);
  assert.notEqual(second.headers.get('ETag'), firstEtag);
  const secondPayload = await second.json();
  assert.deepEqual(firstPayload.listings, secondPayload.listings);
  assert.equal(secondPayload.items.listings[0].unitPrice, 7000);
});

test('oversized upload bodies fail with 413 without replacing public data', async () => {
  const env = environment('previous');
  const declared = new Request('https://example.workers.dev/internal/snapshot', {
    method: 'POST', headers: { Authorization: 'Bearer test-secret', 'Content-Length': '1000001' },
    body: JSON.stringify(snapshotWithItems()),
  });
  assert.equal((await worker.fetch(declared, env)).status, 413);
  assert.equal(env.values.get('snapshot'), 'previous');
  const actual = snapshotWithItems();
  actual.padding = 'x'.repeat(1_000_001);
  assert.equal((await worker.fetch(upload(actual), env)).status, 413);
  assert.equal(env.values.get('snapshot'), 'previous');
});

test('catalog verification supports calendar dates and UTC instants while rejecting impossible dates', async () => {
  for (const date of ['2026-10-14', '2026-10-14T00:00:00Z']) {
    const data = snapshotWithItems();
    data.items.catalog.verifiedAt = date;
    Object.assign(data.items.catalog.entries[0], { officialVerified: true,
      officialSource: { url: 'https://lineageclassic.plaync.com/ko-kr/gameguide', verifiedAt: date } });
    const stored = await storedSnapshot(data);
    assert.equal(stored.items.catalog.verifiedAt, date);
    assert.equal(stored.items.catalog.entries[0].officialSource.verifiedAt, date);
  }
  for (const date of ['2026-02-30', '2026-13-01', 'not-a-date']) {
    const data = snapshotWithItems(), env = environment('previous');
    data.items.catalog.verifiedAt = date;
    assert.equal((await worker.fetch(upload(data), env)).status, 400, date);
    assert.equal(env.values.get('snapshot'), 'previous');
  }
});

test('enchantment follows the store range and non-enhanceable catalog items remain zero or unknown', async () => {
  for (const enchant of [null, 0, 15]) {
    const data = snapshotWithItems();
    data.items.listings[0].enchant = enchant;
    assert.equal((await storedSnapshot(data)).items.listings[0].enchant, enchant);
  }
  for (const enchant of [-1, 16]) {
    const data = snapshotWithItems(), env = environment('previous');
    data.items.listings[0].enchant = enchant;
    assert.equal((await worker.fetch(upload(data), env)).status, 400);
    assert.equal(env.values.get('snapshot'), 'previous');
  }
  const data = snapshotWithItems();
  data.items.catalog.entries[0].enhanceable = false;
  data.items.listings.forEach((row, index) => { row.enchant = index === 0 ? null : 0; });
  const stored = await storedSnapshot(data);
  assert.equal(stored.items.catalog.entries[0].enhanceable, false);
  assert.equal(stored.items.groups.length, 2);
  data.items.listings[0].enchant = 1;
  const env = environment('previous');
  assert.equal((await worker.fetch(upload(data), env)).status, 400);
  assert.equal(env.values.get('snapshot'), 'previous');
});

test('item coverage preserves anonymous exclusion counts and derives matched count from retained rows', async () => {
  const data = snapshotWithItems();
  data.items.listings.push(structuredClone(data.items.listings[1]));
  Object.assign(data.items.coverage, { matchedCount: 999, excludedCount: 9, rawCount: 12,
    unmappedCount: 5, ambiguousCount: 3, invalidCount: 1,
    excludedCounts: { unmapped: 5, ambiguous: 3, invalid: 1, seller: 'PRIVATE-COUNTER' } });
  Object.assign(data.items.sources[0], { rawCount: 10, eligibleTotal: 1,
    unmappedCount: 5, ambiguousCount: 3, invalidCount: 1,
    excludedCounts: { unmapped: 5, ambiguous: 3, invalid: 1, seller: 'PRIVATE-COUNTER' } });
  const stored = await storedSnapshot(data), coverage = stored.items.coverage;
  assert.equal(coverage.matchedCount, 3);
  assert.equal(coverage.excludedCount, 9);
  assert.equal(coverage.rawCount, 12);
  assert.deepEqual(coverage.excludedCounts, { unmapped: 5, ambiguous: 3, invalid: 1 });
  assert.equal(stored.items.sources[0].rawCount, 10);
  assert.equal(stored.items.sources[0].eligibleTotal, 1);
  assert.equal(stored.items.sources[0].unmappedCount, 5);
  assert.deepEqual(stored.items.sources[0].excludedCounts, { unmapped: 5, ambiguous: 3, invalid: 1 });
  assert.ok(!JSON.stringify(stored).includes('PRIVATE-'));
  data.items.coverage.excludedCount = -1;
  data.items.coverage.rawCount = true;
  data.items.sources[0].rawCount = 'PRIVATE-BAD-COUNT';
  const sanitized = await storedSnapshot(data);
  assert.equal(sanitized.items.coverage.excludedCount, 0);
  assert.equal(sanitized.items.coverage.rawCount, 0);
  assert.equal(sanitized.items.sources[0].rawCount, 0);
  assert.ok(!JSON.stringify(sanitized).includes('PRIVATE-'));
});

test('the repository item catalog is compatible with public Worker retention', async () => {
  const catalog = JSON.parse(readFileSync(new URL('../market/item_catalog.json', import.meta.url), 'utf8'));
  const data = snapshotWithItems(), entry = catalog.entries[0];
  data.items.catalog = catalog;
  data.items.listings.forEach(row => {
    row.itemId = entry.id;
    row.itemName = entry.name;
    row.enchant = entry.enhanceable === false ? 0 : 6;
  });
  const stored = await storedSnapshot(data), retained = stored.items.catalog;
  assert.equal(retained.entries.length, catalog.entries.length);
  assert.equal(retained.mappingVersion, catalog.mappingVersion);
  assert.equal(retained.version, catalog.mappingVersion);
  assert.equal(retained.verifiedAt, catalog.verifiedAt);
  assert.equal(retained.officialVerifiedCount, catalog.entries.filter(item => item.officialVerified).length);
  assert.equal(stored.items.listings[0].itemName, entry.name);
  assert.equal(stored.items.sources.find(source => source.id === 'itembay').sourceUrl,
    'https://www.itembay.com/item/sell/game-3828/type-4');
  assert.ok(retained.entries.every(item => item.aliases.every(alias => typeof alias === 'string')));
  for (const item of catalog.entries) {
    const safe = retained.entries.find(value => value.id === item.id);
    assert.equal(safe.enhanceable, item.enhanceable !== false);
    if (!item.officialVerified) {
      assert.equal(safe.officialVerified, false);
      assert.equal(safe.referenceUrl, null);
    }
  }
});

test('verified official guide API documents retain exact safe NC URLs', async () => {
  for (const title of officialGuideTitles) {
    for (const segment of [title, encodeURIComponent(title)]) {
      const url = 'https://lineageclassic.plaync.com/api/v2/lineageclassic/guide/' + segment;
      const data = snapshotWithItems(), entry = data.items.catalog.entries[0];
      entry.officialVerified = true;
      entry.referenceUrl = url;
      entry.officialSource = { url, verifiedAt: '2026-10-14' };
      data.items.catalog.sources = [{ url, name: 'PRIVATE-SOURCE-NAME' }];
      const stored = await storedSnapshot(data), safe = stored.items.catalog.entries[0];
      assert.equal(safe.officialVerified, true, url);
      assert.equal(safe.referenceUrl, new URL(url).href);
      assert.equal(safe.officialSource.url, new URL(url).href);
      assert.equal(safe.officialSource.verifiedAt, '2026-10-14');
      assert.equal(stored.items.catalog.sources[0].url, new URL(url).href);
      assert.equal(stored.items.catalog.officialVerifiedCount, 1);
      assert.ok(!JSON.stringify(stored).includes('PRIVATE-'));
    }
  }
});

test('official guidebook views allow one known document title parameter', async () => {
  for (const title of officialGuideTitles) {
    for (const parameter of [title, encodeURIComponent(title)]) {
      const sourceUrl = 'https://lineageclassic.plaync.com/api/v2/lineageclassic/guide/' + encodeURIComponent(title);
      const referenceUrl = 'https://lineageclassic.plaync.com/ko-kr/guidebook/view?title=' + parameter;
      const data = snapshotWithItems(), entry = data.items.catalog.entries[0];
      entry.officialVerified = true;
      entry.referenceUrl = referenceUrl;
      entry.officialSource = { url: sourceUrl, verifiedAt: data.generatedAt };
      const stored = await storedSnapshot(data), safe = stored.items.catalog.entries[0];
      assert.equal(safe.officialVerified, true, referenceUrl);
      assert.equal(safe.referenceUrl, new URL(referenceUrl).href);
      assert.equal(safe.officialSource.url, sourceUrl);
    }
  }
});

test('unrelated APIs and unsafe guide URLs cannot grant official verification', async () => {
  const host = 'https://lineageclassic.plaync.com';
  const document = encodeURIComponent('방어구');
  const apiPath = '/api/v2/lineageclassic/guide/' + document;
  const viewPath = '/ko-kr/guidebook/view?title=' + document;
  const urls = [
    'http://lineageclassic.plaync.com' + apiPath,
    'https://user:password@lineageclassic.plaync.com' + apiPath,
    'https://lineageclassic.plaync.com.evil.example' + apiPath,
    'https://attacker.example' + apiPath,
    host + apiPath + '?token=PRIVATE-TOKEN',
    host + apiPath + '#PRIVATE-FRAGMENT',
    host + apiPath + '/extra',
    host + apiPath + '%2fextra',
    host + apiPath + '%5cextra',
    host + '/api/v2/lineageclassic/guide/' + encodeURIComponent('확인되지 않은 문서'),
    host + '/api/v2/lineageclassic/users',
    host + '/api/v2/other/guide/' + document,
    host + '/api/v2/lineageclassic/guide/',
    host + '/api/v2/lineageclassic/guide/../guide/' + document,
    host + '/api/v2/lineageclassic/guide/%2e%2e/guide/' + document,
    host + viewPath + '&token=PRIVATE-TOKEN',
    host + viewPath + '&title=' + encodeURIComponent('장신구'),
    host + viewPath + '&title=' + document,
    host + viewPath + '#PRIVATE-FRAGMENT',
    'https://user:password@lineageclassic.plaync.com' + viewPath,
    'https://lineageclassic.plaync.com.evil.example' + viewPath,
    host + '/ko-kr/guidebook/view?title=' + encodeURIComponent('확인되지 않은 문서'),
    host + '/ko-kr/guidebook/view?title=' + 'x'.repeat(81),
    host + '/ko-kr/guidebook/view?Title=' + document,
    host + '/ko-kr/guidebook/view?title=',
    host + '/ko-kr/guidebook/view',
    host + '/ko-kr/other/../guidebook/view?title=' + document,
    host + '/ko-kr/guidebook/view/extra?title=' + document,
    host + '/ko-kr/gameguide?title=' + document,
  ];
  for (const url of urls) {
    const data = snapshotWithItems(), entry = data.items.catalog.entries[0];
    entry.officialVerified = true;
    entry.referenceUrl = url;
    entry.officialSource = { url, verifiedAt: data.generatedAt };
    data.items.catalog.sources = [{ url }];
    const stored = await storedSnapshot(data), safe = stored.items.catalog.entries[0];
    assert.equal(safe.officialVerified, false, url);
    assert.equal(safe.officialSource, null, url);
    assert.equal(safe.referenceUrl, null, url);
    assert.deepEqual(stored.items.catalog.sources, [], url);
    assert.ok(!JSON.stringify(stored).includes('PRIVATE-'), url);
  }
});

test('verified canonical item spellings and parentheses survive public normalization', async () => {
  const examples = [
    { name: '용기의 부츠', guide: '방어구', category: 'armor', enhanceable: true },
    { name: '마나의 지팡이', guide: '무기', category: 'weapon', enhanceable: true },
    { name: '정령의 수정(트리플 애로우)', guide: '요정 마법', category: 'skillbook', enhanceable: false },
    { name: '오우거의 벨트', guide: '장신구', category: 'accessory', enhanceable: false },
    { name: '기술서 (쇼크 스턴)', guide: '기사 마법', category: 'skillbook', enhanceable: false },
  ];
  for (const example of examples) {
    const data = snapshotWithItems(), entry = data.items.catalog.entries[0];
    Object.assign(entry, { name: example.name, aliases: [example.name], category: example.category,
      enhanceable: example.enhanceable, officialVerified: true,
      officialSource: { url: 'https://lineageclassic.plaync.com/api/v2/lineageclassic/guide/' +
        encodeURIComponent(example.guide), verifiedAt: '2026-10-14' } });
    data.items.listings.forEach(row => {
      row.itemName = example.name;
      row.title = 'PRIVATE-ORIGINAL-SUBJECT';
      row.enchant = example.enhanceable ? 6 : null;
    });
    const stored = await storedSnapshot(data);
    assert.equal(stored.items.catalog.entries[0].name, example.name);
    assert.equal(stored.items.catalog.entries[0].officialVerified, true);
    assert.equal(stored.items.groups[0].itemName, example.name);
    assert.ok(stored.items.listings.every(row => row.itemName === example.name && row.title === example.name));
    assert.ok(!JSON.stringify(stored).includes('PRIVATE-'));
  }
});

test('catalog intrinsic blessing metadata preserves valid enums and rejects malformed values', async () => {
  for (const blessing of ['normal', 'blessed', 'cursed', 'unknown', null]) {
    const data = snapshotWithItems();
    data.items.catalog.entries[0].inherentBlessing = blessing;
    if (['normal', 'blessed', 'cursed'].includes(blessing)) {
      data.items.listings.forEach(row => { row.blessing = blessing; });
    }
    const stored = await storedSnapshot(data);
    assert.equal(stored.items.catalog.entries[0].inherentBlessing, blessing);
  }
  assert.equal((await storedSnapshot(snapshotWithItems())).items.catalog.entries[0].inherentBlessing, null);
  for (const blessing of ['unrecognized', false, 1, {}, []]) {
    const data = snapshotWithItems(), env = environment('previous');
    data.items.catalog.entries[0].inherentBlessing = blessing;
    assert.equal((await worker.fetch(upload(data), env)).status, 400, JSON.stringify(blessing));
    assert.equal(env.values.get('snapshot'), 'previous');
  }
});

test('fixed intrinsic blessings constrain item rows while unknown and null preserve observed variants', async () => {
  for (const inherent of ['normal', 'blessed', 'cursed']) {
    const data = snapshotWithItems(), env = environment();
    data.items.catalog.entries[0].inherentBlessing = inherent;
    data.items.listings.forEach(row => { row.blessing = inherent; });
    assert.equal((await worker.fetch(upload(data), env)).status, 200);
    const previous = env.values.get('snapshot');
    assert.ok(JSON.parse(previous).items.listings.every(row => row.blessing === inherent));
    for (const observed of ['normal', 'blessed', 'cursed', 'unknown'].filter(value => value !== inherent)) {
      data.items.listings[0].blessing = observed;
      assert.equal((await worker.fetch(upload(data), env)).status, 400, inherent + ' / ' + observed);
      assert.equal(env.values.get('snapshot'), previous);
    }
  }
  for (const inherent of ['unknown', null]) {
    for (const observed of ['normal', 'blessed', 'cursed', 'unknown']) {
      const data = snapshotWithItems();
      data.items.catalog.entries[0].inherentBlessing = inherent;
      data.items.listings[0].blessing = observed;
      const stored = await storedSnapshot(data);
      assert.equal(stored.items.catalog.entries[0].inherentBlessing, inherent);
      assert.equal(stored.items.listings[0].blessing, observed);
    }
  }
});
