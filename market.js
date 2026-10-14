(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const scheduledStaticUpdates = document.querySelector('meta[name="market-static-updates"]')?.content === 'scheduled';
  const currency = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 1 });
  const integer = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const timeFormatter = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false });
  const dateFormatter = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  const sourceDefaults = [{ id: 'barotem', name: '바로템' }, { id: 'itembay', name: '아이템베이' }, { id: 'itemmania', name: '아이템매니아' }];
  let favorites;
  try { const saved = JSON.parse(localStorage.getItem('classic-market-favorites') || '[]'); favorites = new Set(Array.isArray(saved) ? saved.filter((item) => typeof item === 'string') : []); } catch { favorites = new Set(); }
  const state = { data: null, kind: 'all', server: 'all', comparison: '', search: '', sort: 'price-asc', favoritesOnly: false, favorites, loading: false, mode: 'api', lastFetchError: false };

  function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function append(parent, ...children) { children.forEach((child) => parent.appendChild(child)); return parent; }
  function number(value) { return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null; }
  function money(value) { const amount = number(value); return amount === null ? '—' : currency.format(amount) + '원'; }
  function validDate(value) { if (!value) return null; const date = new Date(value); return Number.isFinite(date.getTime()) ? date : null; }
  function time(value, full = false) { const date = validDate(value); return date ? (full ? dateFormatter : timeFormatter).format(date) : '아직 수집 전'; }
  function stale(value) { const date = validDate(value); return !date || Date.now() - date.getTime() > 20 * 60 * 1000; }
  function median(values) { const clean = values.map(number).filter((value) => value !== null).sort((a, b) => a - b); if (!clean.length) return null; const mid = Math.floor(clean.length / 2); return clean.length % 2 ? clean[mid] : (clean[mid - 1] + clean[mid]) / 2; }
  function safeUrl(value) { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; } }
  function listings() { return state.data ? state.data.listings.filter((listing) => (listing.kind === 'ask' || listing.kind === 'completed') && number(listing.unitPrice) !== null) : []; }
  function sourceName(id) { const source = state.data?.sources.find((entry) => entry.id === id) || sourceDefaults.find((entry) => entry.id === id); return source?.name || id || '출처 확인 중'; }
  function baseListings() { const search = state.search.trim().toLocaleLowerCase(); return listings().filter((listing) => (state.server === 'all' || listing.server === state.server) && (!state.favoritesOnly || state.favorites.has(listing.server)) && (!search || [listing.server, listing.title, sourceName(listing.source)].some((value) => typeof value === 'string' && value.toLocaleLowerCase().includes(search)))); }
  function filteredServers() { if (!state.data) return []; const search = state.search.trim().toLocaleLowerCase(); const matches = new Set(baseListings().map((listing) => listing.server)); return state.data.servers.filter((server) => (state.server === 'all' || state.server === server.name) && (!state.favoritesOnly || state.favorites.has(server.name)) && (!search || server.name.toLocaleLowerCase().includes(search) || matches.has(server.name))); }

  function refreshOptions() {
    const servers = state.data?.servers || [];
    const names = new Set(servers.map((server) => server.name));
    if (state.server !== 'all' && !names.has(state.server)) state.server = 'all';
    if (!names.has(state.comparison)) state.comparison = servers[0]?.name || '';
    $('server-filter').replaceChildren(element('option', '', '전체 서버'));
    $('server-filter').firstChild.value = 'all';
    $('comparison-server').replaceChildren();
    if (!servers.length) { const empty = element('option', '', '서버 선택'); empty.value = ''; $('comparison-server').append(empty); }
    servers.forEach((server) => {
      const option = element('option', '', server.name); option.value = server.name; $('server-filter').append(option);
      const compareOption = option.cloneNode(true); $('comparison-server').append(compareOption);
    });
    $('server-filter').value = state.server;
    $('comparison-server').value = state.comparison;
  }

  function renderStatus() {
    const sources = state.data?.sources?.length ? state.data.sources : sourceDefaults.map((source) => ({ ...source, status: 'pending' }));
    $('source-status').replaceChildren();
    sources.forEach((source) => {
      const isUnconnected = source.id === 'itemmania' && source.status === 'pending';
      const isStale = source.status === 'ok' && stale(source.updatedAt);
      const status = source.status === 'error' ? 'error' : isStale ? 'stale' : source.status === 'ok' ? 'ok' : 'pending';
      const card = element('div', 'source-card');
      const iconClass = sourceDefaults.some((entry) => entry.id === source.id) ? source.id : '';
      const icon = element('span', 'source-icon ' + iconClass, source.name?.slice(0, 1) || '·'); icon.setAttribute('aria-hidden', 'true');
      const label = element('div'); append(label, element('p', 'source-name', source.name || '거래소'), element('p', 'source-time', isUnconnected ? '아직 미연동' : '수집 ' + time(source.updatedAt)));
      const badge = element('div', 'source-state ' + status);
      const statusText = isUnconnected ? '연동 준비' : { ok: '수집 정상', stale: '갱신 지연', pending: '수집 대기', error: '수집 실패' }[status];
      append(badge, element('strong', '', statusText), element('small', '', status === 'ok' ? integer.format(Number(source.sampleCount) || 0) + '개 수집' : source.updatedAt ? '이전 수집값 유지' : '가격 표시 없음'));
      append(card, icon, label, badge); $('source-status').append(card);
    });
    const successCount = sources.filter((source) => source.status === 'ok' && !stale(source.updatedAt)).length;
    const hasPrices = listings().length > 0;
    $('collection-status').textContent = successCount ? successCount + '개 거래소 수집 중 · 공개 매물 표본' : hasPrices ? '갱신 대기 · 이전 수집 결과 표시' : '첫 수집 결과 대기 중';
    $('last-update').textContent = '최근 성공 수집 ' + time(state.data?.lastSuccessfulUpdateAt || state.data?.generatedAt, true) + ' (한국 시간)';
    updateCountdown();
    const notice = $('global-notice'); notice.classList.toggle('error', state.lastFetchError);
    if (state.lastFetchError) { notice.textContent = state.data ? '시세판 연결이 일시적으로 지연되고 있습니다. 마지막으로 불러온 결과를 유지하며 자동으로 다시 확인합니다.' : '시세 정보를 불러오지 못했습니다. 연결을 자동으로 다시 확인합니다. 아직 수집된 가격을 표시하지 않습니다.'; }
    else if (state.mode === 'static' && !scheduledStaticUpdates) { notice.textContent = '저장된 수집 결과를 보는 미리보기입니다. 새 가격을 자동으로 수집하려면 수집 서버가 실행되어야 합니다.'; }
    else if (state.data && sources.some((source) => !(source.id === 'itemmania' && source.status === 'pending') && (source.status !== 'ok' || stale(source.updatedAt)))) { notice.textContent = '일부 거래소의 수집이 대기 중이거나 지연되고 있습니다. 거래소별 수집 시각을 확인하세요. 이전 수집값이 있는 경우 그대로 표시합니다.'; }
    else if (state.mode === 'static' && scheduledStaticUpdates) { notice.textContent = '10분 간격 갱신을 목표로 합니다. 예약 작업 지연 시 이전 시세가 표시될 수 있습니다.'; }
    else if (state.data && !hasPrices) { notice.textContent = '첫 수집 결과를 준비하고 있습니다. 가격 정보가 확인되면 자동으로 표시됩니다.'; }
    else { notice.textContent = ''; }
    notice.hidden = !notice.textContent;
  }

  function updateCountdown() {
    const date = validDate(state.data?.nextUpdateAt);
    if (state.mode === 'static' && !scheduledStaticUpdates) { $('next-update').textContent = '자동 수집 미연결'; return; }
    if (!date) { $('next-update').textContent = '다음 수집 일정 확인 중'; return; }
    const seconds = Math.ceil((date.getTime() - Date.now()) / 1000);
    if (seconds <= 0) { $('next-update').textContent = '다음 수집 결과 대기 중'; return; }
    const minutes = Math.floor(seconds / 60);
    $('next-update').textContent = '다음 수집 ' + (minutes ? minutes + '분 ' : '') + (seconds % 60) + '초 후';
  }

  function renderMetrics() {
    const rows = baseListings();
    const asks = rows.filter((listing) => listing.kind === 'ask');
    const completed = rows.filter((listing) => listing.kind === 'completed');
    $('metric-median').textContent = money(median(asks.map((listing) => listing.unitPrice)));
    $('metric-lowest').textContent = money(asks.length ? Math.min(...asks.map((listing) => listing.unitPrice)) : null);
    $('metric-listings').textContent = integer.format(asks.length) + '개';
    $('metric-completed').textContent = integer.format(completed.length) + '개';
    $('metric-server-count').textContent = new Set(rows.map((listing) => listing.server)).size + '개 서버 · 공개 매물 표본';
  }

  function renderServers() {
    const grid = $('server-grid'); grid.replaceChildren();
    const servers = filteredServers();
    if (!servers.length) { grid.append(element('p', 'empty-state', state.favoritesOnly ? '관심 서버가 없습니다. 서버 카드의 별을 눌러 추가하세요.' : state.data?.servers.length ? '검색 조건에 맞는 서버가 없습니다.' : '아직 수집된 서버가 없습니다. 첫 수집 결과를 기다리고 있습니다.')); }
    servers.forEach((server) => {
      const price = number(server.askMedian);
      const card = element('article', 'server-card' + (server.name === state.comparison ? ' selected' : '') + (price === null ? ' unavailable' : ''));
      const head = element('div', 'server-card-head');
      const title = element('button', 'server-card-title', server.name); title.type = 'button'; title.setAttribute('aria-label', server.name + ' 서버 시세 비교');
      title.addEventListener('click', () => { state.comparison = server.name; state.server = server.name; $('comparison-server').value = server.name; $('server-filter').value = server.name; renderContent(); });
      const favorite = element('button', 'favorite-button', state.favorites.has(server.name) ? '★' : '☆'); favorite.type = 'button'; favorite.dataset.server = server.name; favorite.setAttribute('aria-pressed', String(state.favorites.has(server.name))); favorite.setAttribute('aria-label', server.name + ' 관심 서버 ' + (state.favorites.has(server.name) ? '해제' : '추가'));
      favorite.addEventListener('click', () => {
        if (state.favorites.has(server.name)) state.favorites.delete(server.name); else state.favorites.add(server.name);
        try { localStorage.setItem('classic-market-favorites', JSON.stringify([...state.favorites])); } catch { /* Favorites remain available for this page session. */ }
        renderContent(); const nextFocus = [...document.querySelectorAll('.favorite-button')].find((button) => button.dataset.server === server.name); (nextFocus || $('favorites-toggle')).focus({ preventScroll: true }); $('live-status').textContent = server.name + ' 관심 서버 ' + (state.favorites.has(server.name) ? '추가됨' : '해제됨');
      });
      append(head, title, favorite);
      const priceLabel = element('p', 'server-price', price === null ? '판매 호가 없음' : currency.format(price)); if (price !== null) priceLabel.append(element('small', '', '원'));
      const range = element('p', 'server-range', number(server.minAsk) !== null && number(server.maxAsk) !== null ? currency.format(server.minAsk) + ' ~ ' + currency.format(server.maxAsk) + '원' : '수집한 판매 매물 기준');
      const foot = element('div', 'server-card-foot'); append(foot, element('span', '', '판매 ' + integer.format(Number(server.listingCount) || 0) + '개'), element('span', '', '완료 ' + integer.format(Number(server.completedCount) || 0) + '개'));
      append(card, head, priceLabel, range, foot); grid.append(card);
    });
    $('coverage-note').textContent = state.data?.coverage?.message || '일부 공개 매물을 수집한 참고 가격입니다. 전체 시장 시세와 다를 수 있습니다.';
  }

  function svgElement(tag, attributes, text) { const node = document.createElementNS('http://www.w3.org/2000/svg', tag); Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, String(value))); if (text !== undefined) node.textContent = text; return node; }
  function renderChart(server) {
    const chart = $('trend-chart'); chart.replaceChildren();
    const kind = server?.historyKind === 'completed' ? 'completed' : 'ask';
    const history = (server?.history || []).filter((point) => validDate(point.at) && number(point.value) !== null && (!point.kind || point.kind === kind)).map((point) => ({ ...point, date: validDate(point.at) })).sort((a, b) => a.date - b.date);
    const current = kind === 'completed' ? server?.completedMedian : server?.askMedian;
    $('trend-price').textContent = money(current);
    $('trend-caption').textContent = (kind === 'completed' ? '거래완료 표시' : '판매 호가') + ' 중앙값 / 100만 아데나';
    if (history.length < 2) {
      const empty = element('div', 'chart-empty'); append(empty, element('span', 'chart-empty-icon', '▥'), element('strong', '', history.length ? '첫 번째 가격 기록을 수집했습니다' : '가격 기록을 쌓고 있습니다'), element('p', '', '다음 수집 기록이 쌓이면 가격 흐름을 보여드립니다.')); empty.firstChild.setAttribute('aria-hidden', 'true'); chart.append(empty); return;
    }
    const width = 540, height = 166, left = 5, right = 72, top = 14, bottom = 27;
    const prices = history.map((point) => point.value); let min = Math.min(...prices), max = Math.max(...prices);
    const padding = Math.max((max - min) * .22, max * .01, 1); min -= padding; max += padding;
    const first = history[0].date.getTime(), last = history[history.length - 1].date.getTime();
    const x = (point, index) => left + (last === first ? index / (history.length - 1) : (point.date.getTime() - first) / (last - first)) * (width - left - right);
    const y = (value) => top + (max - value) / (max - min) * (height - top - bottom);
    const svg = svgElement('svg', { viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': server.name + ' 서버 ' + (kind === 'completed' ? '거래완료 표시' : '판매 호가') + ' 중앙값 가격 추이. ' + history.length + '개 실제 수집 기록. 첫 가격 ' + money(history[0].value) + ', 최근 가격 ' + money(history[history.length - 1].value) });
    const defs = svgElement('defs'); const gradient = svgElement('linearGradient', { id: 'trend-fill', x1: '0', y1: '0', x2: '0', y2: '1' }); append(gradient, svgElement('stop', { offset: '0%', 'stop-color': '#2abb8b', 'stop-opacity': '.15' }), svgElement('stop', { offset: '100%', 'stop-color': '#2abb8b', 'stop-opacity': '0' })); defs.append(gradient); svg.append(defs);
    [0, .5, 1].forEach((fraction) => { const value = max - fraction * (max - min); const pointY = y(value); svg.append(svgElement('line', { x1: left, x2: width - right + 8, y1: pointY, y2: pointY, class: 'chart-grid' })); svg.append(svgElement('text', { x: width - right + 17, y: pointY + 3 }, integer.format(value))); });
    const points = history.map((point, index) => [x(point, index), y(point.value)]); const path = points.map(([pointX, pointY], index) => (index ? 'L' : 'M') + pointX.toFixed(2) + ' ' + pointY.toFixed(2)).join(' ');
    svg.append(svgElement('path', { d: path + ' L' + points[points.length - 1][0] + ' ' + (height - bottom) + ' L' + left + ' ' + (height - bottom) + ' Z', class: 'chart-fill' })); svg.append(svgElement('path', { d: path, class: 'chart-line' }));
    const lastPoint = points[points.length - 1]; svg.append(svgElement('circle', { cx: lastPoint[0], cy: lastPoint[1], r: 3.4, class: 'chart-point' }));
    svg.append(svgElement('text', { x: left, y: height - 6 }, time(history[0].at)));
    svg.append(svgElement('text', { x: width - right, y: height - 6, 'text-anchor': 'end' }, time(history[history.length - 1].at)));
    chart.append(svg);
  }

  function renderComparison() {
    const server = state.data?.servers.find((entry) => entry.name === state.comparison);
    $('comparison-label').textContent = server?.name || '서버 선택';
    const container = $('source-comparison'); container.replaceChildren();
    if (!server) { container.append(element('p', 'empty-state', '수집된 서버가 있으면 거래소별 가격을 비교할 수 있습니다.')); renderChart(null); return; }
    const stats = server.sourceStats || [];
    const sources = state.data.sources.length ? state.data.sources : sourceDefaults;
    sources.forEach((source) => {
      const stat = stats.find((entry) => entry.id === source.id);
      const row = element('div', 'comparison-row'); row.append(element('span', 'comparison-name', source.name));
      ['ask', 'completed'].forEach((kind) => {
        const value = kind === 'ask' ? stat?.askMedian : stat?.completedMedian;
        const cell = element('div', 'comparison-value' + (kind === 'completed' ? ' completed' : ''));
        append(cell, element('span', '', kind === 'ask' ? '판매 호가' : '거래완료 표시'), element('strong', number(value) === null ? 'comparison-unavailable' : '', number(value) === null ? '수집값 없음' : money(value)));
        row.append(cell);
      });
      container.append(row);
    });
    renderChart(server);
  }

  function quantity(value) { const amount = number(value); if (amount === null) return '—'; if (amount >= 10000) return currency.format(amount / 10000) + '만 아데나'; return integer.format(amount) + ' 아데나'; }
  function renderListings() {
    const rows = baseListings().filter((listing) => state.kind === 'all' || listing.kind === state.kind).sort((a, b) => state.sort === 'recent' ? (validDate(b.observedAt)?.getTime() || 0) - (validDate(a.observedAt)?.getTime() || 0) : state.sort === 'price-desc' ? b.unitPrice - a.unitPrice : a.unitPrice - b.unitPrice);
    $('listing-count').textContent = integer.format(rows.length) + '개 매물 · 공개 표본';
    const body = $('listing-body'); body.replaceChildren();
    if (!rows.length) { const row = element('tr'); const cell = element('td', 'table-empty', state.data && listings().length ? '현재 조건에 맞는 매물이 없습니다.' : '아직 수집된 매물이 없습니다. 가격을 만들어 표시하지 않고 실제 수집 결과를 기다립니다.'); cell.colSpan = 7; row.append(cell); body.append(row); return; }
    rows.forEach((listing) => {
      const row = element('tr');
      const titleCell = element('td'); append(titleCell, element('span', 'listing-server', listing.server || '서버 미확인'), element('span', 'listing-title', listing.title || '아데나 매물'));
      const sourceCell = element('td', 'listing-source', sourceName(listing.source));
      const kindCell = element('td'); kindCell.append(element('span', 'kind-pill' + (listing.kind === 'completed' ? ' completed' : ''), listing.kind === 'completed' ? '거래완료 표시' : '판매 호가'));
      const priceCell = element('td', 'number-cell'); const price = element('span', 'unit-price', currency.format(listing.unitPrice)); price.append(element('small', '', '원')); priceCell.append(price);
      const quantityCell = element('td', 'number-cell quantity', quantity(listing.quantity));
      const observedCell = element('td', 'observed', time(listing.observedAt)); observedCell.title = time(listing.observedAt, true) + ' (한국 시간)';
      const linkCell = element('td'); const url = safeUrl(listing.url);
      if (url) { const link = element('a', 'original-link', '원문 ↗'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.setAttribute('aria-label', sourceName(listing.source) + ' ' + (listing.server || '') + ' 매물 원문 새 창에서 보기'); linkCell.append(link); }
      else { linkCell.append(element('span', 'observed', '—')); }
      append(row, titleCell, sourceCell, kindCell, priceCell, quantityCell, observedCell, linkCell); body.append(row);
    });
  }

  function renderContent() { renderMetrics(); renderServers(); renderComparison(); renderListings(); }
  function normalizeSnapshot(data) {
    if (!data || data.schemaVersion !== 1 || !Array.isArray(data.sources) || !Array.isArray(data.servers) || !Array.isArray(data.listings)) throw new Error('Unexpected snapshot');
    return { ...data, sources: data.sources.filter((source) => source && typeof source.id === 'string'), servers: data.servers.filter((server) => server && typeof server.name === 'string'), listings: data.listings.filter((listing) => listing && typeof listing.source === 'string' && typeof listing.server === 'string') };
  }
  async function load() {
    if (state.loading) return;
    state.loading = true;
    try {
      let response = await fetch(state.mode === 'static' ? './data/prices.json' : '/api/prices', { cache: 'no-cache', headers: { Accept: 'application/json' } });
      if (state.mode === 'api' && [404, 405].includes(response.status)) { response = await fetch('./data/prices.json', { cache: 'no-cache', headers: { Accept: 'application/json' } }); state.mode = 'static'; }
      if (!response.ok) throw new Error('Snapshot unavailable');
      const data = normalizeSnapshot(await response.json());
      const changed = !state.data || state.data.generatedAt !== data.generatedAt;
      state.data = data; state.lastFetchError = false;
      if (changed) { refreshOptions(); renderContent(); }
      renderStatus();
      if (changed) $('live-status').textContent = '시세 정보 갱신됨. ' + listings().length + '개 매물을 확인할 수 있습니다.';
    } catch { state.lastFetchError = true; renderStatus(); if (!state.data) renderContent(); }
    finally { state.loading = false; }
  }

  $('search-input').addEventListener('input', (event) => { state.search = event.target.value; renderContent(); });
  $('server-filter').addEventListener('change', (event) => { state.server = event.target.value; if (state.server !== 'all') { state.comparison = state.server; $('comparison-server').value = state.comparison; } renderContent(); });
  $('comparison-server').addEventListener('change', (event) => { state.comparison = event.target.value; renderServers(); renderComparison(); });
  $('sort-filter').addEventListener('change', (event) => { state.sort = event.target.value; renderListings(); });
  $('favorites-toggle').addEventListener('click', () => { state.favoritesOnly = !state.favoritesOnly; $('favorites-toggle').setAttribute('aria-pressed', String(state.favoritesOnly)); renderContent(); });
  document.querySelectorAll('[data-kind]').forEach((button) => button.addEventListener('click', () => { state.kind = button.dataset.kind; document.querySelectorAll('[data-kind]').forEach((tab) => tab.setAttribute('aria-pressed', String(tab === button))); renderListings(); }));
  renderStatus(); load();
  setInterval(() => { if (!document.hidden) load(); }, 30000);
  setInterval(updateCountdown, 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
})();
