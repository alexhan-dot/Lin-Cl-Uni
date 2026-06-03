const ADMIN_STORAGE_KEY = "lineage-classic-university-site-data";
const adminForm = document.querySelector("[data-admin-form]");
const pricingEditor = document.querySelector("[data-pricing-editor]");
const jsonEditor = document.querySelector("[data-json-editor]");
const savebar = document.querySelector(".admin-savebar");
const statusText = document.querySelector("[data-admin-status]");

function adminClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function adminIsPlainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function adminMergeData(base, override) {
  if (Array.isArray(base)) return Array.isArray(override) ? override : base;
  if (!adminIsPlainObject(base)) return override ?? base;

  const merged = { ...base };
  Object.keys(override || {}).forEach((key) => {
    merged[key] = adminMergeData(base[key], override[key]);
  });
  return merged;
}

function getSavedData() {
  const defaults = adminClone(window.LINEAGE_SITE_DATA || {});
  try {
    const saved = JSON.parse(localStorage.getItem(ADMIN_STORAGE_KEY) || "null");
    return saved ? adminMergeData(defaults, saved) : defaults;
  } catch {
    return defaults;
  }
}

let adminData = getSavedData();

function getByPath(source, path) {
  return path.split(".").reduce((current, key) => current?.[key], source);
}

function setByPath(source, path, value) {
  const keys = path.split(".");
  const lastKey = keys.pop();
  let target = source;

  keys.forEach((key) => {
    if (!adminIsPlainObject(target[key])) target[key] = {};
    target = target[key];
  });

  target[lastKey] = value;
}

function escapeAttribute(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStatus(message, type = "info") {
  if (statusText) statusText.textContent = message;
  savebar?.classList.toggle("is-saved", type === "saved");
  savebar?.classList.toggle("is-error", type === "error");
}

function syncJsonEditor() {
  if (jsonEditor) {
    jsonEditor.value = JSON.stringify(adminData, null, 2);
  }
}

function renderBaseFields() {
  document.querySelectorAll("[data-field]").forEach((field) => {
    const value = getByPath(adminData, field.dataset.field);
    if (field instanceof HTMLTextAreaElement || field instanceof HTMLInputElement) {
      field.value = value ?? "";
    }
  });
}

function renderPricingEditor() {
  if (!pricingEditor) return;

  pricingEditor.innerHTML = (adminData.pricing?.cards || [])
    .map(
      (card, index) => `
        <div class="price-editor-row" data-price-index="${index}">
          <h3>${index + 1}. ${escapeAttribute(card.title || "수강료 카드")}</h3>
          <label>
            과정명
            <input data-price-field="title" type="text" value="${escapeAttribute(card.title)}" />
          </label>
          <label>
            가격
            <input data-price-field="price" type="text" value="${escapeAttribute(card.price)}" />
          </label>
          <label class="wide-field">
            설명
            <textarea data-price-field="text" rows="2">${escapeAttribute(card.text)}</textarea>
          </label>
          <label>
            버튼 문구
            <input data-price-field="cta" type="text" value="${escapeAttribute(card.cta || "상담하기")}" />
          </label>
          <label>
            배지 문구
            <input data-price-field="tag" type="text" value="${escapeAttribute(card.tag || "")}" />
          </label>
          <label class="checkbox-field">
            <input data-price-field="featured" type="checkbox" ${card.featured ? "checked" : ""} />
            추천 카드로 강조
          </label>
        </div>
      `,
    )
    .join("");
}

function renderAdmin() {
  renderBaseFields();
  renderPricingEditor();
  syncJsonEditor();
}

function saveAdminData() {
  localStorage.setItem(ADMIN_STORAGE_KEY, JSON.stringify(adminData));
  setStatus("저장 완료. 사이트 미리보기에서 변경 내용을 확인할 수 있습니다.", "saved");
}

function downloadSiteData() {
  const content = `window.LINEAGE_SITE_DATA = ${JSON.stringify(adminData, null, 2)};\n`;
  const blob = new Blob([content], { type: "text/javascript;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = "site-data.js";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus("배포용 site-data.js 파일을 생성했습니다.", "saved");
}

function applyJsonEditor() {
  try {
    adminData = JSON.parse(jsonEditor.value);
    renderAdmin();
    setStatus("JSON 내용을 적용했습니다. 저장하면 미리보기에 반영됩니다.", "saved");
  } catch (error) {
    setStatus(`JSON 오류: ${error.message}`, "error");
  }
}

document.addEventListener("input", (event) => {
  const target = event.target;

  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    if (target.dataset.field) {
      setByPath(adminData, target.dataset.field, target.value);
      syncJsonEditor();
      setStatus("수정 중입니다. 저장 버튼을 누르면 반영됩니다.");
    }

    if (target.dataset.priceField) {
      const row = target.closest("[data-price-index]");
      const index = Number(row?.dataset.priceIndex);
      const field = target.dataset.priceField;
      if (Number.isInteger(index) && adminData.pricing?.cards?.[index]) {
        adminData.pricing.cards[index][field] = target.value;
        syncJsonEditor();
        setStatus("수강료를 수정 중입니다. 저장 버튼을 누르면 반영됩니다.");
      }
    }
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.dataset.priceField !== "featured") return;

  const row = target.closest("[data-price-index]");
  const index = Number(row?.dataset.priceIndex);
  if (Number.isInteger(index) && adminData.pricing?.cards?.[index]) {
    adminData.pricing.cards[index].featured = target.checked;
    syncJsonEditor();
    setStatus("추천 카드 표시를 수정 중입니다. 저장 버튼을 누르면 반영됩니다.");
  }
});

adminForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  saveAdminData();
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!(button instanceof HTMLElement)) return;

  const action = button.dataset.action;
  if (action === "download") downloadSiteData();
  if (action === "apply-json") applyJsonEditor();
  if (action === "preview") window.open("index.html", "_blank", "noopener,noreferrer");
  if (action === "reset") {
    const shouldReset = window.confirm("관리자 저장값을 초기화하고 기본 데이터로 되돌릴까요?");
    if (!shouldReset) return;
    localStorage.removeItem(ADMIN_STORAGE_KEY);
    adminData = getSavedData();
    renderAdmin();
    setStatus("기본 데이터로 초기화했습니다.", "saved");
  }
});

renderAdmin();
