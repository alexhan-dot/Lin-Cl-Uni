// Static assets + one cached snapshot. The collector runs on a Mac mini or VM.
const MAX_BYTES = 1_000_000;
const ALLOWED_SOURCES = new Set(['barotem', 'itembay']);
const PRICE_PATH = '/api/prices';

const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
});

function sameToken(actual, expected) {
  if (!actual || !expected || actual.length !== expected.length) return false;
  let mismatch = 0;
  for (let i = 0; i < actual.length; i++) mismatch |= actual.charCodeAt(i) ^ expected.charCodeAt(i);
  return mismatch === 0;
}

function validateSnapshot(data) {
  if (data?.schemaVersion !== 1 || !Array.isArray(data.listings) || !Array.isArray(data.sources)
      || !Array.isArray(data.servers) || data.listings.length > 3000 || data.servers.length > 100
      || !Number.isFinite(Date.parse(data.generatedAt)) || data.intervalSeconds !== 600) {
    throw new Error('Invalid snapshot schema');
  }
  // Only normalized price fields are retained. Seller fields never enter the public KV value.
  const listings = data.listings.map(row => {
    if (!ALLOWED_SOURCES.has(row.source) || !['ask', 'completed'].includes(row.kind)
        || ![row.unitPrice, row.priceKRW, row.quantity].every(n => Number.isFinite(n) && n > 0)
        || typeof row.server !== 'string' || row.server.length > 80
        || typeof row.id !== 'string' || row.id.length > 120) throw new Error('Invalid listing');
    const url = new URL(row.url);
    if (url.protocol !== 'https:' || url.username || url.password
        || !['www.barotem.com', 'www.itembay.com'].includes(url.hostname)) throw new Error('Invalid source URL');
    return { id: row.id, source: row.source, server: row.server, kind: row.kind,
      unitPrice: row.unitPrice, priceKRW: row.priceKRW, quantity: row.quantity,
      observedAt: row.observedAt, url: url.href,
      title: row.kind === 'completed' ? '아데나 완료 매물' : '아데나 매물' };
  });
  return { schemaVersion: 1, game: '리니지 클래식', intervalSeconds: 600,
    generatedAt: data.generatedAt, nextUpdateAt: data.nextUpdateAt,
    lastSuccessfulUpdateAt: data.lastSuccessfulUpdateAt,
    sources: data.sources.map(s => ({ id: s.id, name: s.name, status: s.status,
      updatedAt: s.updatedAt, error: s.error ? '수집 실패; 이전 데이터를 표시합니다.' : null,
      sampleCount: s.sampleCount, completedCount: s.completedCount, sourceUrl: s.sourceUrl })),
    servers: data.servers, coverage: data.coverage, listings };
}

async function digest(text) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return '"' + Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('') + '"';
}

async function readSnapshot(env, request) {
  const text = env.MARKET ? await env.MARKET.get('snapshot') : null;
  if (text) return text;
  // A packaged real snapshot allows a first preview before the Mac uploader starts.
  const bootstrap = await env.ASSETS.fetch(new Request(new URL('/data/prices.json', request.url)));
  return bootstrap.ok ? await bootstrap.text() : null;
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
      const body = await request.text();
      if (new TextEncoder().encode(body).length > MAX_BYTES) return jsonResponse({ error: 'Too large' }, 413);
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
