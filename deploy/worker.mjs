// Static assets + one cached snapshot. The collector runs on a Mac mini or VM.
const MAX_BYTES = 1_000_000;
const ALLOWED_SOURCES = new Set(['barotem', 'itembay']);
const PRICE_PATH = '/api/prices';
const SOURCE_INFO = {
  barotem: { name: '바로템', sourceUrl: 'https://www.barotem.com/product/lists/2382r902' },
  itembay: { name: '아이템베이', sourceUrl: 'https://www.itembay.com/item/sell/game-3828/type-3' },
  itemmania: { name: '아이템매니아', sourceUrl: 'https://www.itemmania.com/' },
};
const ITEM_BLESSINGS = new Set(['normal', 'blessed', 'cursed', 'unknown']);
// These document titles have been read from the official Classic guide API.
const OFFICIAL_GUIDE_TITLES = new Set(['무기', '방어구', '장신구', '레벨 퀘스트', '던전', '몽환의 섬',
  '요정 마법', '기사 마법', '아이템 소개', '필드 사냥터']);

const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
});

function sameToken(actual, expected) {
  if (!actual || !expected || actual.length !== expected.length) return false;
  let mismatch = 0;
  for (let i = 0; i < actual.length; i++) mismatch |= actual.charCodeAt(i) ^ expected.charCodeAt(i);
  return mismatch === 0;
}

function validTime(value, nullable = false) {
  if (nullable && value == null) return null;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
      || !Number.isFinite(Date.parse(value))) throw new Error('Invalid timestamp');
  return value;
}

function verifiedDate(value) {
  if (value == null) return null;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const date = new Date(value + 'T00:00:00Z');
    if (Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value) return value;
    throw new Error('Invalid verification date');
  }
  return validTime(value);
}

function safeName(value, max = 80) {
  if (typeof value !== 'string' || !value.trim() || value.length > max
      || /[<>@\/:?#\\\u0000-\u001f]/.test(value)
      || /(?:https?|카카오|카톡|텔레그램|전화|연락처)|(?:\b0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}\b)/i.test(value)) {
    throw new Error('Invalid canonical name');
  }
  return value.trim();
}

const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const median = values => {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b), middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : sorted[middle - 1] + (sorted[middle] - sorted[middle - 1]) / 2;
};

function normalizedListing(row, multiplier) {
  if (!row || !ALLOWED_SOURCES.has(row.source) || !['ask', 'completed'].includes(row.kind)
      || ![row.unitPrice, row.priceKRW, row.quantity].every(n => Number.isFinite(n) && n > 0)
      || (multiplier === 1 && !Number.isSafeInteger(row.quantity))) throw new Error('Invalid listing');
  const expected = row.priceKRW / row.quantity * multiplier;
  if (!Number.isFinite(expected) || Math.abs(row.unitPrice - expected) > Math.max(0.00001, expected * 1e-7)) {
    throw new Error('Inconsistent unit price');
  }
  const match = typeof row.id === 'string' && row.id.match(new RegExp('^' + row.source + ':([0-9]{1,32})$'));
  if (!match) throw new Error('Invalid public listing identifier');
  const url = new URL(row.url), hostname = row.source === 'barotem' ? 'www.barotem.com' : 'www.itembay.com';
  if (url.protocol !== 'https:' || url.username || url.password || url.hostname !== hostname || (url.port && url.port !== '443')) {
    throw new Error('Invalid source URL');
  }
  const publicUrl = row.source === 'barotem' ? 'https://www.barotem.com/product/view/' + match[1]
    : 'https://www.itembay.com/item/sell/itemSellDetail?iItemSeq=' + match[1];
  return { id: row.id, source: row.source, server: safeName(row.server, 40), kind: row.kind,
    unitPrice: row.unitPrice, priceKRW: row.priceKRW, quantity: row.quantity,
    observedAt: validTime(row.observedAt), url: publicUrl };
}

function cleanSources(raw, listings, items = false) {
  if (!Array.isArray(raw) || raw.length > 3) throw new Error('Invalid source metadata');
  const seen = new Set();
  const result = raw.map(source => {
    if (!source || !Object.hasOwn(SOURCE_INFO, source.id) || seen.has(source.id)
        || !['ok', 'error', 'pending'].includes(source.status)) throw new Error('Invalid source metadata');
    seen.add(source.id);
    const rows = listings.filter(row => row.source === source.id), completedCount = rows.filter(row => row.kind === 'completed').length;
    const info = SOURCE_INFO[source.id];
    const updatedAt = validTime(source.updatedAt, true);
    if (rows.length && (updatedAt === null || source.status === 'pending')) throw new Error('Missing source provenance');
    return { id: source.id, name: info.name, status: source.status,
      updatedAt, error: source.status === 'error' ? '수집 실패; 이전 데이터를 표시합니다.' : null,
      sampleCount: rows.length, completedCount, stale: source.status !== 'ok' || source.stale === true,
      pagesFetched: count(source.pagesFetched), totalListings: Number.isSafeInteger(source.totalListings) && source.totalListings >= 0 ? source.totalListings : null,
      rejectedCount: count(source.rejectedCount), warnings: source.warnings?.length ? ['일부 매물이 표본에서 제외되었습니다.'] : [],
      ...(items ? { rawCount: count(source.rawCount), eligibleTotal: count(source.eligibleTotal),
        unmappedCount: count(source.unmappedCount ?? source.excludedCounts?.unmapped),
        ambiguousCount: count(source.ambiguousCount ?? source.excludedCounts?.ambiguous),
        invalidCount: count(source.invalidCount ?? source.excludedCounts?.invalid),
        excludedCounts: { unmapped: count(source.excludedCounts?.unmapped ?? source.unmappedCount),
          ambiguous: count(source.excludedCounts?.ambiguous ?? source.ambiguousCount),
          invalid: count(source.excludedCounts?.invalid ?? source.invalidCount) } } : {}),
      sourceUrl: items && source.id === 'itembay' ? 'https://www.itembay.com/item/sell/game-3828/type-4'
        : items && source.id === 'barotem' ? 'https://www.barotem.com/product/lists/2381r870' : info.sourceUrl };
  });
  if (listings.some(row => !seen.has(row.source))) throw new Error('Missing source provenance');
  return result;
}

function stats(rows, sources) {
  const asks = rows.filter(row => row.kind === 'ask').map(row => row.unitPrice);
  const completed = rows.filter(row => row.kind === 'completed').map(row => row.unitPrice);
  return { count: rows.length, listingCount: asks.length, completedCount: completed.length,
    askMedian: median(asks), completedMedian: median(completed), minAsk: asks.length ? Math.min(...asks) : null,
    maxAsk: asks.length ? Math.max(...asks) : null,
    sourceStats: sources.filter(source => rows.some(row => row.source === source.id)).map(source => {
      const sourceRows = rows.filter(row => row.source === source.id);
      const sourceAsks = sourceRows.filter(row => row.kind === 'ask').map(row => row.unitPrice);
      const sourceCompleted = sourceRows.filter(row => row.kind === 'completed').map(row => row.unitPrice);
      return { id: source.id, name: source.name, count: sourceRows.length, listingCount: sourceAsks.length,
        completedCount: sourceCompleted.length, askMedian: median(sourceAsks), completedMedian: median(sourceCompleted),
        updatedAt: source.updatedAt, status: source.status };
    }) };
}

function cleanCoverage(raw, items = false, matchedCount = null) {
  return { mode: 'sample', pagesPerSource: count(raw?.pagesPerSource), maxRows: count(raw?.maxRows),
    rejectedCount: count(raw?.rejectedCount), unmatchedCount: count(raw?.unmatchedCount), ambiguousCount: count(raw?.ambiguousCount),
    ...(items ? { matchedCount: matchedCount ?? count(raw?.matchedCount), excludedCount: count(raw?.excludedCount),
      rawCount: count(raw?.rawCount), unmappedCount: count(raw?.unmappedCount), invalidCount: count(raw?.invalidCount),
      excludedCounts: { unmapped: count(raw?.excludedCounts?.unmapped), ambiguous: count(raw?.excludedCounts?.ambiguous),
        invalid: count(raw?.excludedCounts?.invalid) } } : {}),
    message: items ? '이름·강화·축복과 수량이 확인된 단일 품목의 일부 표본입니다.' : '일반 매물과 완료표시의 일부 표본이며 전체 시장을 대표하지 않습니다.' };
}

function officialUrl(value) {
  if (value == null) return null;
  if (typeof value !== 'string' || value.length > 2048 || !/^https:\/\//i.test(value) || /[\\\u0000-\u001f]/.test(value)) return null;
  // URL() removes literal and encoded dot segments. Check the original path
  // first so an unrelated route cannot become an allowed route by traversal.
  const pathAt = value.indexOf('/', 8), rawPath = pathAt < 0 ? '' : value.slice(pathAt).split(/[?#]/, 1)[0];
  try {
    if (rawPath.split('/').map(segment => decodeURIComponent(segment))
      .some(segment => segment === '.' || segment === '..' || /[/\\]/.test(segment))) return null;
  } catch { return null; }
  let url;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || url.port) return null;
  if (url.hostname === 'lineageclassic.plaync.com') {
    if (url.pathname === '/ko-kr/guidebook/view') {
      const params = [...url.searchParams.entries()];
      if (params.length !== 1 || params[0][0] !== 'title' || params[0][1].length > 80
          || !OFFICIAL_GUIDE_TITLES.has(params[0][1])) return null;
    } else if (url.pathname.startsWith('/api/v2/lineageclassic/guide/')) {
      if (url.search) return null;
      let title;
      try { title = decodeURIComponent(url.pathname.slice('/api/v2/lineageclassic/guide/'.length)); }
      catch { return null; }
      if (!OFFICIAL_GUIDE_TITLES.has(title)) return null;
    } else if (!url.pathname.startsWith('/ko-kr/') || url.search) return null;
  } else if (url.hostname !== 'about.ncsoft.com' || !url.pathname.startsWith('/news/article/') || url.search) return null;
  return url.href;
}

function cleanCatalog(raw) {
  if (!raw || !Array.isArray(raw.entries) || raw.entries.length > 1000) throw new Error('Invalid item catalog');
  const seen = new Set();
  const entries = raw.entries.map(entry => {
    if (!entry || typeof entry.id !== 'string' || !/^lc-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(entry.id) || seen.has(entry.id)) {
      throw new Error('Invalid canonical item identifier');
    }
    seen.add(entry.id);
    const inherentBlessing = entry.inherentBlessing ?? null;
    if (inherentBlessing !== null && !ITEM_BLESSINGS.has(inherentBlessing)) throw new Error('Invalid inherent item blessing');
    const referenceUrl = officialUrl(entry.referenceUrl);
    const sourceUrl = officialUrl(entry.officialSource?.url);
    const verified = entry.officialVerified === true && sourceUrl != null;
    const aliases = Array.isArray(entry.aliases) ? [...new Set(entry.aliases.slice(0, 40).map(alias => safeName(typeof alias === 'string' ? alias : alias?.value)))] : [];
    return { id: entry.id, name: safeName(entry.name), aliases, category: entry.category ? safeName(entry.category, 40) : null,
      enhanceable: entry.enhanceable !== false,
      inherentBlessing,
      referenceUrl: verified ? (referenceUrl || sourceUrl) : null, officialVerified: verified,
      verification: verified ? 'official_verified' : 'marketplace_only',
      officialSource: verified ? { url: sourceUrl, title: '리니지 클래식 공식 자료', verifiedAt: verifiedDate(entry.officialSource.verifiedAt) } : null };
  });
  const sources = Array.isArray(raw.sources) ? raw.sources.slice(0, 20).flatMap(source => {
    const url = officialUrl(source?.url);
    return url ? [{ url, name: '리니지 클래식 공식 자료' }] : [];
  }) : [];
  const mappingVersion = safeName(raw.mappingVersion, 80);
  return { version: mappingVersion, mappingVersion, verifiedAt: verifiedDate(raw.verifiedAt),
    officialVerifiedCount: entries.filter(entry => entry.officialVerified).length,
    verificationScope: '공개 매물에서 확인한 품목과 별칭이며 공식명 검증 여부를 별도로 표시합니다.',
    game: { id: 'lineage-classic', name: '리니지 클래식' }, sources, entries };
}

function cleanItems(raw) {
  if (!raw || raw.intervalSeconds !== 3600 || !Array.isArray(raw.listings) || raw.listings.length > 3000
      || !Array.isArray(raw.groups) || raw.groups.length > 3000) throw new Error('Invalid item snapshot');
  const catalog = cleanCatalog(raw.catalog), byId = new Map(catalog.entries.map(entry => [entry.id, entry]));
  const seen = new Set(), listings = [];
  for (const row of raw.listings) {
    const normalized = normalizedListing(row, 1), entry = byId.get(row.itemId);
    if (!entry || row.itemName !== entry.name || (row.enchant !== null && (!Number.isSafeInteger(row.enchant) || row.enchant < 0 || row.enchant > 15))
        || (!entry.enhanceable && row.enchant !== null && row.enchant !== 0)
        || (entry.inherentBlessing !== null && entry.inherentBlessing !== 'unknown' && row.blessing !== entry.inherentBlessing)
        || !ITEM_BLESSINGS.has(row.blessing)) throw new Error('Invalid mapped item');
    const key = JSON.stringify([row.source, row.id, row.kind]);
    if (seen.has(key)) continue;
    seen.add(key);
    listings.push({ ...normalized, itemId: entry.id, itemName: entry.name, enchant: row.enchant,
      blessing: row.blessing, title: entry.name });
  }
  const sources = cleanSources(raw.sources, listings, true), grouped = new Map();
  for (const row of listings) {
    const key = JSON.stringify([row.itemId, row.server, row.enchant, row.blessing]);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  }
  const groups = [...grouped].map(([id, rows]) => ({ id, itemId: rows[0].itemId, itemName: rows[0].itemName,
    server: rows[0].server, enchant: rows[0].enchant, blessing: rows[0].blessing, ...stats(rows, sources) }));
  return { units: 'KRW_PER_ITEM', mappingVersion: catalog.mappingVersion, intervalSeconds: 3600, generatedAt: validTime(raw.generatedAt), nextUpdateAt: validTime(raw.nextUpdateAt),
    lastSuccessfulUpdateAt: validTime(raw.lastSuccessfulUpdateAt, true),
    stale: raw.stale === true || sources.some(source => source.status === 'error'), sources, listings, groups,
    coverage: cleanCoverage(raw.coverage, true, listings.length), catalog };
}

function validateSnapshot(data) {
  if (data?.schemaVersion !== 1 || !Array.isArray(data.listings) || !Array.isArray(data.sources)
      || !Array.isArray(data.servers) || data.listings.length > 3000 || data.servers.length > 100
      || data.intervalSeconds !== 600) {
    throw new Error('Invalid snapshot schema');
  }
  // Only normalized price fields are retained. Seller fields never enter the public KV value.
  const generatedAt = validTime(data.generatedAt), seen = new Set();
  const listings = data.listings.flatMap(row => {
    const listing = normalizedListing(row, 1_000_000), key = JSON.stringify([listing.source, listing.id, listing.kind]);
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ ...listing, title: row.kind === 'completed' ? '아데나 완료 매물' : '아데나 매물' }];
  });
  const sources = cleanSources(data.sources, listings), previous = new Map(data.servers.map(server => [server?.name, server]));
  const servers = [...new Set(listings.map(row => row.server))].sort().map(name => {
    const rows = listings.filter(row => row.server === name), prior = previous.get(name), values = stats(rows, sources);
    const historyKind = values.askMedian !== null ? 'ask' : 'completed';
    const history = Array.isArray(prior?.history) ? prior.history.slice(-144).map(point => {
      if (!Number.isFinite(point?.value) || point.value <= 0 || !['ask', 'completed'].includes(point.kind ?? prior.historyKind)) {
        throw new Error('Invalid price history');
      }
      const at = validTime(point.at);
      if (Date.parse(at) > Date.parse(generatedAt)) throw new Error('Invalid price history');
      return { at, value: point.value, kind: point.kind ?? prior.historyKind };
    }) : [];
    return { name, ...values, historyKind, history };
  });
  const value = { schemaVersion: 1, game: '리니지 클래식', units: 'KRW_PER_1M_ADENA', intervalSeconds: 600,
    generatedAt, nextUpdateAt: validTime(data.nextUpdateAt), lastSuccessfulUpdateAt: validTime(data.lastSuccessfulUpdateAt, true),
    stale: data.stale === true || sources.some(source => source.status === 'error'),
    sources, servers, coverage: cleanCoverage(data.coverage), listings };
  if (Object.hasOwn(data, 'items')) value.items = cleanItems(data.items);
  return value;
}

async function digest(text) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return '"' + Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('') + '"';
}

async function readSnapshot(env, request) {
  const text = env.MARKET ? await env.MARKET.get('snapshot') : null;
  if (text) {
    try { return JSON.stringify(validateSnapshot(JSON.parse(text))); } catch { /* Try a safe packaged snapshot. */ }
  }
  // A packaged real snapshot allows a first preview before the Mac uploader starts.
  const bootstrap = await env.ASSETS.fetch(new Request(new URL('/data/prices.json', request.url)));
  if (!bootstrap.ok) return null;
  try { return JSON.stringify(validateSnapshot(await bootstrap.json())); } catch { return null; }
}

async function boundedBody(request) {
  if (!request.body) return '';
  const reader = request.body.getReader(), chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(body);
}

export default {
  async fetch(request, env, context = { waitUntil() {} }) {
    const url = new URL(request.url);
    if (url.pathname === '/internal/snapshot') {
      if (request.method !== 'POST') return jsonResponse({ error: 'Method not allowed' }, 405);
      if (!env.MARKET_UPLOAD_TOKEN || !env.MARKET) return jsonResponse({ error: 'Upload not configured' }, 503);
      const token = request.headers.get('Authorization')?.replace(/^Bearer /, '');
      if (!sameToken(token, env.MARKET_UPLOAD_TOKEN)) return jsonResponse({ error: 'Unauthorized' }, 401);
      if (Number(request.headers.get('Content-Length')) > MAX_BYTES) return jsonResponse({ error: 'Too large' }, 413);
      const body = await boundedBody(request);
      if (body === null) return jsonResponse({ error: 'Too large' }, 413);
      let value;
      try { value = validateSnapshot(JSON.parse(body)); }
      catch { return jsonResponse({ error: 'Invalid snapshot' }, 400); }
      await env.MARKET.put('snapshot', JSON.stringify(value));
      if (globalThis.caches?.default) {
        context.waitUntil(caches.default.delete(new Request(new URL(PRICE_PATH, request.url))));
      }
      return jsonResponse({ ok: true, generatedAt: value.generatedAt, listings: value.listings.length });
    }
    if (url.pathname === PRICE_PATH) {
      if (!['GET', 'HEAD'].includes(request.method)) return jsonResponse({ error: 'Method not allowed' }, 405);
      const cacheKey = new Request(new URL(PRICE_PATH, request.url));
      let response = globalThis.caches?.default ? await caches.default.match(cacheKey) : null;
      if (!response) {
        const text = await readSnapshot(env, request);
        if (!text) return jsonResponse({ error: '수집 데이터를 준비 중입니다.' }, 503);
        response = new Response(text, { headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Cache-Control': 'public, max-age=30, s-maxage=60',
          'ETag': await digest(text), 'X-Content-Type-Options': 'nosniff',
        } });
        if (globalThis.caches?.default) context.waitUntil(caches.default.put(cacheKey, response.clone()));
      }
      if (request.headers.get('If-None-Match') === response.headers.get('ETag')) {
        return new Response(null, { status: 304, headers: response.headers });
      }
      return request.method === 'HEAD' ? new Response(null, { headers: response.headers }) : response;
    }
    if (url.pathname.startsWith('/internal/') || url.pathname.startsWith('/api/')) {
      return jsonResponse({ error: 'Not found' }, 404);
    }
    return env.ASSETS.fetch(request);
  },
};
