const API_BASE = "";
const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/jpg", "image/webp"];
const MAX_FILE_MB = 10;

function $(selector, scope = document) {
  return scope.querySelector(selector);
}

function showLoading(message) {
  const overlay = $("#loading-overlay");
  if (!overlay) return;
  const text = $("#loading-text");
  if (text && message) text.textContent = message;
  overlay.classList.remove("hidden");
}

function hideLoading() {
  const overlay = $("#loading-overlay");
  if (overlay) overlay.classList.add("hidden");
}

function showError(el, message) {
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden");
}

function clearError(el) {
  if (!el) return;
  el.textContent = "";
  el.classList.add("hidden");
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    data = null;
  }
  if (!response.ok) {
    const detail = (data && data.detail) || response.statusText || "Request failed.";
    throw new Error(detail);
  }
  return data;
}

function scoreClass(score) {
  if (score >= 70) return "";
  if (score >= 40) return "mid";
  return "low";
}

function formatDate(isoString) {
  try {
    const d = new Date(isoString);
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (_) {
    return isoString;
  }
}

function initIndexPage() {
  const dropzone = $("#dropzone");
  if (!dropzone) return;

  const fileInput = $("#file-input");
  const previewWrap = $("#preview-wrap");
  const previewImg = $("#preview-img");
  const previewFilename = $("#preview-filename");
  const analyzeBtn = $("#analyze-image-btn");
  const imageError = $("#image-error");
  let selectedFile = null;

  function validateAndPreview(file) {
    clearError(imageError);
    if (!file) return;

    if (!ALLOWED_TYPES.includes(file.type)) {
      showError(imageError, "Unsupported file type. Please use PNG, JPG, JPEG, or WEBP.");
      analyzeBtn.disabled = true;
      return;
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      showError(imageError, `File is too large. Maximum size is ${MAX_FILE_MB} MB.`);
      analyzeBtn.disabled = true;
      return;
    }

    selectedFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      previewImg.src = e.target.result;
      previewFilename.textContent = file.name;
      previewWrap.classList.remove("hidden");
      analyzeBtn.disabled = false;
    };
    reader.readAsDataURL(file);
  }

  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => validateAndPreview(fileInput.files[0]));

  ["dragenter", "dragover"].forEach((evtName) => {
    dropzone.addEventListener(evtName, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((evtName) => {
    dropzone.addEventListener(evtName, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    validateAndPreview(file);
  });

  analyzeBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    clearError(imageError);
    analyzeBtn.disabled = true;

    try {
      showLoading("Reading ingredient label (OCR)\u2026");
      const formData = new FormData();
      formData.append("file", selectedFile);
      const uploadResult = await apiRequest("/upload", {
        method: "POST",
        body: formData,
      });

      showLoading("Asking AI to analyze ingredients\u2026");
      const productName = $("#image-product-name").value.trim();
      const analyzeResult = await apiRequest("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_name: productName,
          ingredients_text: uploadResult.ingredients_text,
          source: "image",
          image_url: uploadResult.image_url,
        }),
      });

      window.location.href = `results.html?id=${analyzeResult.id}`;
    } catch (err) {
      hideLoading();
      showError(imageError, err.message || "Something went wrong. Please try again.");
      analyzeBtn.disabled = false;
    }
  });
}

function renderResults(scan) {
  const container = $("#results-container");
  const analysis = scan.analysis;

  const sourceLabel = { image: "📷 Image Scan", barcode: "🔢 Barcode Lookup", manual: "✍️ Manual Entry" }[
    scan.source
  ] || scan.source;

  const scores = analysis.scores;

  const scoreRow = (label, value) => `
    <div class="score-item">
      <div class="score-label"><span>${label}</span><span>${value}/100</span></div>
      <div class="progress-track">
        <div class="progress-fill ${scoreClass(value)}" style="width:${value}%"></div>
      </div>
    </div>`;

  const prosHtml = analysis.pros.map((p) => `<li>${p}</li>`).join("");
  const consHtml = analysis.cons.map((c) => `<li>${c}</li>`).join("");

  const showAlternatives =
    analysis.processing_level !== "Minimally Processed" &&
    analysis.alternatives &&
    analysis.alternatives.length > 0;
  const alternativesHtml = showAlternatives
    ? analysis.alternatives.map((a) => `<li>${a}</li>`).join("")
    : "";

  const ingredientCards = analysis.ingredients
    .map(
      (ing) => `
      <div class="ingredient-card">
        <h3>${ing.name}</h3>
        <div class="label">Explanation</div>
        <p>${ing.explanation}</p>
        <div class="label">Purpose</div>
        <p>${ing.purpose}</p>
      </div>`
    )
    .join("");

  const levelBadgeClass =
    analysis.processing_level === "Minimally Processed"
      ? ""
      : analysis.processing_level === "Ultra-Processed"
      ? "badge-danger"
      : "badge-warning";

  container.innerHTML = `
    <div class="results-header">
      <div>
        <h1>${scan.product_name}</h1>
        <div class="results-meta">${sourceLabel} &middot; ${formatDate(scan.created_at)}</div>
      </div>
      <span class="badge ${levelBadgeClass}">${analysis.processing_level}</span>
    </div>

    ${scan.image_url ? `<div class="preview-wrap" style="margin-bottom:24px;"><img src="${scan.image_url}" alt="Uploaded label" style="max-height:220px;"/></div>` : ""}

    <div class="card section-block">
      <h2 class="section-title">📝 Product Summary</h2>
      <p>${analysis.product_summary}</p>
    </div>

    <div class="card section-block">
      <h2 class="section-title">📊 Food Score</h2>
      <div class="score-grid">
        ${scoreRow("Overall Score", scores.overall)}
        ${scoreRow("Processing Score", scores.processing)}
        ${scoreRow("Ingredient Score", scores.ingredient)}
      </div>
    </div>

    <div class="grid-2 section-block">
      <div class="card">
        <h2 class="section-title">✅ Pros</h2>
        <ul class="pill-list pros">${prosHtml || "<li>None identified.</li>"}</ul>
      </div>
      <div class="card">
        <h2 class="section-title">⚠️ Cons</h2>
        <ul class="pill-list cons">${consHtml || "<li>None identified.</li>"}</ul>
      </div>
    </div>

    <div class="section-block">
      <h2 class="section-title">🧪 Ingredient Breakdown</h2>
      <div class="ingredient-grid">${ingredientCards}</div>
    </div>

    ${
      showAlternatives
        ? `<div class="card section-block">
      <h2 class="section-title">🔄 Better Alternatives</h2>
      <ul class="pill-list alternatives">${alternativesHtml}</ul>
    </div>`
        : ""
    }

    <div class="actions-row">
      <a href="index.html" class="btn btn-secondary">Scan Another Product</a>
      <a href="history.html" class="btn btn-secondary">View History</a>
    </div>
  `;
}

async function initResultsPage() {
  const container = $("#results-container");
  if (!container) return;

  const params = new URLSearchParams(window.location.search);
  const id = params.get("id");

  if (!id) {
    container.innerHTML = `<div class="empty-state"><div class="dz-icon">🤔</div><p>No scan selected.</p><a class="btn btn-primary" href="index.html">Start a New Scan</a></div>`;
    return;
  }

  showLoading("Loading results\u2026");
  try {
    const scan = await apiRequest(`/history/${id}`);
    hideLoading();
    renderResults(scan);
  } catch (err) {
    hideLoading();
    container.innerHTML = `<div class="empty-state"><div class="dz-icon">😕</div><p>${
      err.message || "Could not load this scan."
    }</p><a class="btn btn-primary" href="index.html">Start a New Scan</a></div>`;
  }
}

async function initHistoryPage() {
  const content = $("#history-content");
  if (!content) return;

  try {
    const scans = await apiRequest("/history");
    if (!scans || scans.length === 0) {
      content.innerHTML = `
        <div class="empty-state">
          <div class="dz-icon">🗂️</div>
          <p>No scans yet. Analyze a product to see it appear here.</p>
          <a class="btn btn-primary" href="index.html">Start a New Scan</a>
        </div>`;
      return;
    }

    const items = scans
      .map(
        (s) => `
        <div class="history-item" data-id="${s.id}">
          <div class="history-item-main">
            <h3>${s.product_name}</h3>
            <div class="meta">${{ image: "📷 Image", barcode: "🔢 Barcode", manual: "✍️ Manual" }[s.source] || s.source} &middot; ${formatDate(
          s.created_at
        )}</div>
          </div>
          <div class="history-score">
            <div class="progress-track" style="width:80px;">
              <div class="progress-fill ${scoreClass(s.overall_score)}" style="width:${s.overall_score}%"></div>
            </div>
            <span>${s.overall_score}</span>
          </div>
        </div>`
      )
      .join("");

    content.innerHTML = `<div class="history-list">${items}</div>`;

    content.querySelectorAll(".history-item").forEach((el) => {
      el.addEventListener("click", () => {
        window.location.href = `results.html?id=${el.dataset.id}`;
      });
    });
  } catch (err) {
    content.innerHTML = `<div class="alert alert-error">${
      err.message || "Could not load history."
    }</div>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initIndexPage();
  initResultsPage();
  initHistoryPage();
});
