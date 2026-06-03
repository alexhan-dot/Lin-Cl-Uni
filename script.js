const STORAGE_KEY = "lineage-classic-university-site-data";
const body = document.body;
const header = document.querySelector("[data-header]");
const menuButton = document.querySelector("[data-menu-button]");
const nav = document.querySelector("[data-nav]");

const iconPaths = {
  layers: `
    <path d="M12 3 4 7l8 4 8-4-8-4Z" />
    <path d="M4 12l8 4 8-4M4 17l8 4 8-4" />
  `,
  bag: `
    <path d="M5 7h14l-1 13H6L5 7Z" />
    <path d="M8 7a4 4 0 0 1 8 0M9 12h6M9 16h4" />
  `,
  scale: `
    <path d="M12 3v18M5 8h14M7 8l-3 7h6L7 8ZM17 8l-3 7h6l-3-7Z" />
  `,
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function isPlainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function mergeData(base, override) {
  if (Array.isArray(base)) return Array.isArray(override) ? override : base;
  if (!isPlainObject(base)) return override ?? base;

  const merged = { ...base };
  Object.keys(override || {}).forEach((key) => {
    merged[key] = mergeData(base[key], override[key]);
  });
  return merged;
}

function loadSiteData() {
  const defaults = clone(window.LINEAGE_SITE_DATA || {});
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return saved ? mergeData(defaults, saved) : defaults;
  } catch {
    return defaults;
  }
}

const siteData = loadSiteData();

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setText(selector, value, root = document) {
  const element = root.querySelector(selector);
  if (element) element.textContent = value ?? "";
}

function setButtonLabel(selector, value) {
  const link = document.querySelector(selector);
  if (!link) return;
  const svg = link.querySelector("svg")?.cloneNode(true);
  link.replaceChildren();
  if (svg) link.append(svg);
  link.append(document.createTextNode(value ?? ""));
}

function renderMeta() {
  document.title = siteData.meta?.title || siteData.brand?.name || "리니지 클래식 대학교";
  const description = document.querySelector('meta[name="description"]');
  if (description && siteData.meta?.description) {
    description.setAttribute("content", siteData.meta.description);
  }
}

function renderHeader() {
  setText(".brand strong", siteData.brand?.name);
  setText(".brand small", siteData.brand?.subtitle);
  document.querySelector(".brand")?.setAttribute("aria-label", `${siteData.brand?.name || "사이트"} 홈`);

  const navLabels = siteData.nav || [];
  nav?.querySelectorAll("a").forEach((link, index) => {
    if (navLabels[index]) link.textContent = navLabels[index];
  });
}

function renderHero() {
  setText(".hero-copy .eyebrow", siteData.hero?.eyebrow);
  setText("#hero-title", siteData.hero?.title);
  setText(".hero-lede", siteData.hero?.lede);
  setButtonLabel(".hero-actions [data-kakao-chat]", siteData.hero?.kakaoCta);
  setButtonLabel(".hero-actions .button.primary", siteData.hero?.consultCta);
  setButtonLabel(".hero-actions .button.secondary", siteData.hero?.curriculumCta);

  setText(".status-top span", siteData.status?.label);
  setText(".status-top strong", siteData.status?.value);
  setText(".status-line span", siteData.status?.lineLabel);

  const statusGrid = document.querySelector(".status-grid");
  if (statusGrid) {
    statusGrid.innerHTML = (siteData.status?.stats || [])
      .map(
        (item) => `
          <div>
            <dt>${escapeHtml(item.label)}</dt>
            <dd>${escapeHtml(item.value)}</dd>
          </div>
        `,
      )
      .join("");
  }
}

function renderNotices() {
  const strip = document.querySelector(".notice-strip");
  if (!strip) return;
  strip.innerHTML = (siteData.notices || [])
    .map(
      (item) => `
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.text)}</span>
        </div>
      `,
    )
    .join("");
}

function renderUrgency() {
  const section = document.querySelector("[data-urgency-section]");
  const bar = document.querySelector("[data-conversion-bar]");
  const urgency = siteData.urgency || {};

  if (!urgency.enabled) {
    section?.setAttribute("hidden", "");
    bar?.setAttribute("hidden", "");
    return;
  }

  section?.removeAttribute("hidden");
  bar?.removeAttribute("hidden");

  if (section) {
    section.innerHTML = `
      <div class="urgency-copy">
        <p class="eyebrow">${escapeHtml(urgency.eyebrow)}</p>
        <span class="urgency-ribbon">${escapeHtml(urgency.ribbon)}</span>
        <h2>${escapeHtml(urgency.title)}</h2>
        <p>${escapeHtml(urgency.text)}</p>
        <div class="urgency-actions">
          <a class="button kakao" href="#contact" data-kakao-chat>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 5C6.9 5 3 8.1 3 12c0 2.5 1.6 4.7 4 5.9L6.4 21l3.3-1.8c.7.1 1.5.2 2.3.2 5.1 0 9-3.1 9-7s-3.9-7.4-9-7.4Z" />
            </svg>
            ${escapeHtml(urgency.primaryCta)}
          </a>
          <a class="button secondary" href="#pricing">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 12h16M12 4v16M6 6l12 12M18 6 6 18" />
            </svg>
            ${escapeHtml(urgency.secondaryCta)}
          </a>
        </div>
      </div>

      <div class="urgency-panel">
        <div class="urgency-panel-top">
          <div>
            <span>${escapeHtml(urgency.deadlineLabel)}</span>
            <strong>${escapeHtml(urgency.deadlineValue)}</strong>
          </div>
          <div>
            <span>${escapeHtml(urgency.slotLabel)}</span>
            <strong>${escapeHtml(urgency.slotValue)}</strong>
          </div>
        </div>
        <div class="urgency-stat-grid">
          ${(urgency.stats || [])
            .map(
              (stat) => `
                <div>
                  <span>${escapeHtml(stat.label)}</span>
                  <strong>${escapeHtml(stat.value)}</strong>
                </div>
              `,
            )
            .join("")}
        </div>
        <div class="loss-box">
          <h3>${escapeHtml(urgency.lossTitle)}</h3>
          <p>${escapeHtml(urgency.lossText)}</p>
        </div>
      </div>

      <div class="loss-grid">
        ${(urgency.losses || [])
          .map(
            (item) => `
              <article>
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(item.text)}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    `;
  }

  if (bar) {
    bar.innerHTML = `
      <div class="conversion-copy">
        <span>${escapeHtml(urgency.stripLabel)}</span>
        <strong>${escapeHtml(urgency.stripTitle)}</strong>
        <p>${escapeHtml(urgency.stripText)}</p>
      </div>
      <a class="button kakao compact-conversion" href="#contact" data-kakao-chat>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5C6.9 5 3 8.1 3 12c0 2.5 1.6 4.7 4 5.9L6.4 21l3.3-1.8c.7.1 1.5.2 2.3.2 5.1 0 9-3.1 9-7s-3.9-7.4-9-7.4Z" />
        </svg>
        ${escapeHtml(urgency.stripCta)}
      </a>
    `;
  }
}

function renderPrograms() {
  const section = document.querySelector("#programs");
  const programs = siteData.programs || {};
  if (!section) return;

  setText(".section-head .eyebrow", programs.eyebrow, section);
  setText(".section-head h2", programs.title, section);
  setText(".section-head p:not(.eyebrow)", programs.text, section);

  const grid = section.querySelector(".program-grid");
  if (!grid) return;
  grid.innerHTML = (programs.cards || [])
    .map(
      (card) => `
        <article class="program-card">
          <div class="card-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">${iconPaths[card.icon] || iconPaths.layers}</svg>
          </div>
          <h3>${escapeHtml(card.title)}</h3>
          <p>${escapeHtml(card.text)}</p>
          <ul>
            ${(card.bullets || []).map((bullet) => `<li>${escapeHtml(bullet)}</li>`).join("")}
          </ul>
        </article>
      `,
    )
    .join("");
}

function renderOperations() {
  const section = document.querySelector("#operations");
  const operations = siteData.operations || {};
  if (!section) return;

  setText(".section-head .eyebrow", operations.eyebrow, section);
  setText(".section-head h2", operations.title, section);
  setText(".section-head p:not(.eyebrow)", operations.text, section);
  setText(".board-head .eyebrow", operations.liveEyebrow, section);
  setText(".board-head h3", operations.liveTitle, section);
  setText(".live-badge", operations.liveBadge, section);

  const timeline = section.querySelector(".timeline");
  if (timeline) {
    timeline.innerHTML = (operations.steps || [])
      .map(
        (step, index) => `
          <div class="timeline-step">
            <span>${String(index + 1).padStart(2, "0")}</span>
            <div>
              <h3>${escapeHtml(step.title)}</h3>
              <p>${escapeHtml(step.text)}</p>
            </div>
          </div>
        `,
      )
      .join("");
  }

  renderQueue();
}

function renderQueue() {
  const queueList = document.querySelector("[data-queue-list]");
  if (!queueList) return;

  queueList.innerHTML = (siteData.queueItems || [])
    .map(
      (item) => `
        <article class="queue-item">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.meta)}</span>
          </div>
          <span class="queue-chip ${escapeHtml(item.tone)}">${escapeHtml(item.status)}</span>
        </article>
      `,
    )
    .join("");
}

function renderPricing() {
  const section = document.querySelector("#pricing");
  const pricing = siteData.pricing || {};
  if (!section) return;

  setText(".section-head .eyebrow", pricing.eyebrow, section);
  setText(".section-head h2", pricing.title, section);
  setText(".section-head p:not(.eyebrow)", pricing.text, section);

  const grid = section.querySelector(".pricing-grid");
  if (!grid) return;
  grid.innerHTML = (pricing.cards || [])
    .map(
      (card) => `
        <article class="price-card${card.featured ? " featured" : ""}">
          ${card.tag ? `<span class="tag">${escapeHtml(card.tag)}</span>` : ""}
          <h3>${escapeHtml(card.title)}</h3>
          <p class="price">${escapeHtml(card.price)}</p>
          <p>${escapeHtml(card.text)}</p>
          <a class="text-link" href="#contact">${escapeHtml(card.cta || "상담하기")}</a>
        </article>
      `,
    )
    .join("");
}

function renderFaq() {
  const section = document.querySelector(".faq-section");
  const faq = siteData.faq || {};
  if (!section) return;

  setText(".section-head .eyebrow", faq.eyebrow, section);
  setText(".section-head h2", faq.title, section);

  const list = section.querySelector(".faq-list");
  if (!list) return;
  list.innerHTML = (faq.items || [])
    .map(
      (item) => `
        <details>
          <summary>
            ${escapeHtml(item.question)}
            <span aria-hidden="true"></span>
          </summary>
          <p>${escapeHtml(item.answer)}</p>
        </details>
      `,
    )
    .join("");
}

function renderContact() {
  const section = document.querySelector("#contact");
  const contactSection = siteData.contactSection || {};
  if (!section) return;

  setText(".contact-copy .eyebrow", contactSection.eyebrow, section);
  setText(".contact-copy h2", contactSection.title, section);
  setText(".contact-copy p:last-child", contactSection.text, section);
  setButtonLabel(".contact-actions [data-kakao-chat]", contactSection.kakaoCta);
  setButtonLabel('.contact-actions a[href^="mailto:"]', contactSection.emailCta);
  setButtonLabel('.contact-actions a[href="#top"]', contactSection.topCta);

  const emailLink = section.querySelector('.contact-actions a[href^="mailto:"]');
  if (emailLink instanceof HTMLAnchorElement && siteData.contact?.email) {
    emailLink.href = `mailto:${siteData.contact.email}`;
  }
}

function renderFooter() {
  const footerItems = document.querySelectorAll(".site-footer p");
  if (footerItems[0]) footerItems[0].textContent = siteData.footer?.copyright || "";
  if (footerItems[1]) footerItems[1].textContent = siteData.footer?.disclaimer || "";
}

function setupKakaoChat() {
  const kakaoUrl = siteData.contact?.kakaoUrl || "";
  const isConfigured = kakaoUrl && !kakaoUrl.includes("REPLACE_WITH_YOUR_CODE");

  document.querySelectorAll("[data-kakao-chat]").forEach((link) => {
    if (!(link instanceof HTMLAnchorElement)) return;

    if (isConfigured) {
      link.href = kakaoUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.removeAttribute("aria-disabled");
      return;
    }

    link.href = "#contact";
    link.setAttribute("aria-disabled", "true");
    link.addEventListener("click", (event) => {
      event.preventDefault();
      window.alert("카카오톡 상담 링크가 아직 설정되지 않았습니다. admin.html에서 카카오톡 링크를 입력하거나 site-data.js의 contact.kakaoUrl을 교체해주세요.");
    });
  });
}

function renderSite() {
  renderMeta();
  renderHeader();
  renderHero();
  renderNotices();
  renderUrgency();
  renderPrograms();
  renderOperations();
  renderPricing();
  renderFaq();
  renderContact();
  renderFooter();
  setupKakaoChat();
}

function setMenu(open) {
  body.classList.toggle("menu-open", open);
  menuButton?.setAttribute("aria-expanded", String(open));
  menuButton?.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
}

menuButton?.addEventListener("click", () => {
  setMenu(!body.classList.contains("menu-open"));
});

nav?.addEventListener("click", (event) => {
  if (event.target instanceof HTMLAnchorElement) {
    setMenu(false);
  }
});

window.addEventListener(
  "scroll",
  () => {
    header?.classList.toggle("is-scrolled", window.scrollY > 24);
  },
  { passive: true },
);

renderSite();
