/* global chrome */

const CAPTURE_DELAY_MS = 600;
const CAPTURE_TIMEOUT_MS = 180_000;
const SCRIPT_TIMEOUT_MS = 10_000;
const DOWNLOAD_URL_REVOKE_DELAY_MS = 60_000;
const MAX_CANVAS_DIMENSION = 32_767;
const MAX_CANVAS_PIXELS = 268_435_456;
const CAPTURE_STYLE_ID = "__superweb2pdf_capture_style__";

const statusEl = document.getElementById("status");
const fullPageBtn = document.getElementById("captureFullPage");
const visibleBtn = document.getElementById("captureVisible");
const progressWrapEl = document.getElementById("progressWrap");
const progressBarEl = document.getElementById("progressBar");
const progressTextEl = document.getElementById("progressText");

function setStatus(msg, level) {
  statusEl.textContent = msg;
  statusEl.className = level || "";
}

function setProgress(percent, text) {
  const safePercent = Math.max(0, Math.min(100, Math.round(percent || 0)));
  progressWrapEl.hidden = false;
  progressTextEl.hidden = false;
  progressWrapEl.setAttribute("aria-valuenow", String(safePercent));
  progressBarEl.style.width = `${safePercent}%`;
  progressTextEl.textContent = text || `${safePercent}%`;
}

function resetProgress() {
  progressWrapEl.hidden = true;
  progressTextEl.hidden = true;
  progressWrapEl.setAttribute("aria-valuenow", "0");
  progressBarEl.style.width = "0%";
  progressTextEl.textContent = "";
}

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    d.getFullYear() +
    pad(d.getMonth() + 1) +
    pad(d.getDate()) +
    "-" +
    pad(d.getHours()) +
    pad(d.getMinutes()) +
    pad(d.getSeconds())
  );
}

function buildFilename(url) {
  let hostname = "page";
  try {
    hostname = new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    /* ignore */
  }
  return `superweb2pdf-${hostname}-${timestamp()}.png`;
}

async function dataURLtoBlob(dataURL) {
  const response = await fetch(dataURL);
  if (!response.ok) {
    throw new Error("Failed to decode captured image");
  }
  return response.blob();
}

function downloadBlob(blob, filename) {
  return new Promise((resolve, reject) => {
    const objectURL = URL.createObjectURL(blob);
    chrome.downloads.download(
      { url: objectURL, filename, saveAs: false },
      (downloadId) => {
        if (chrome.runtime.lastError) {
          URL.revokeObjectURL(objectURL);
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        setTimeout(() => URL.revokeObjectURL(objectURL), DOWNLOAD_URL_REVOKE_DELAY_MS);
        resolve(downloadId);
      }
    );
  });
}

function captureVisibleTab(windowId, deadline) {
  assertNotTimedOut(deadline);
  return withTimeout(
    new Promise((resolve, reject) => {
      chrome.tabs.captureVisibleTab(windowId, { format: "png" }, (dataURL) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!dataURL) {
          reject(new Error("Chrome returned an empty screenshot"));
        } else {
          resolve(dataURL);
        }
      });
    }),
    remainingTime(deadline),
    "Timed out while capturing the visible tab"
  );
}

function getActiveTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (!tabs.length) {
        reject(new Error("No active tab found"));
      } else {
        resolve(tabs[0]);
      }
    });
  });
}

function getTab(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(tab);
      }
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function remainingTime(deadline) {
  return Math.max(1, deadline - Date.now());
}

function assertNotTimedOut(deadline) {
  if (Date.now() >= deadline) {
    throw new Error(
      `Capture timed out after ${Math.round(CAPTURE_TIMEOUT_MS / 1000)} seconds. ` +
        "Try capturing a shorter page or zooming out before retrying."
    );
  }
}

function withTimeout(promise, timeoutMs, timeoutMessage) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
  });

  return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId));
}

async function sleepWithDeadline(ms, deadline) {
  assertNotTimedOut(deadline);
  await withTimeout(sleep(ms), remainingTime(deadline), "Capture timed out while waiting for the page");
}

function validateCapturableTab(tab) {
  if (!tab || typeof tab.id !== "number") {
    throw new Error("No capturable active tab found");
  }

  let protocol = "";
  try {
    protocol = new URL(tab.url || "").protocol;
  } catch (_) {
    /* handled below */
  }

  const supportedProtocols = new Set(["http:", "https:"]);
  if (!supportedProtocols.has(protocol)) {
    throw new Error(
      "This page cannot be captured by the extension. " +
        "Open an http:// or https:// page instead; browser, extension, about:, and file:// pages are restricted."
    );
  }
}

async function ensureSameTab(tabId, originalUrl, deadline) {
  assertNotTimedOut(deadline);
  const tab = await withTimeout(
    getTab(tabId),
    Math.min(SCRIPT_TIMEOUT_MS, remainingTime(deadline)),
    "Timed out while checking the active tab"
  );

  if (tab.url !== originalUrl) {
    throw new Error("Capture cancelled because the tab navigated during capture. Please retry on the final page.");
  }
  return tab;
}

async function runScript(tabId, func, args, step, deadline) {
  assertNotTimedOut(deadline);
  try {
    const injectionResults = await withTimeout(
      chrome.scripting.executeScript({
        target: { tabId },
        func,
        args: args || [],
      }),
      Math.min(SCRIPT_TIMEOUT_MS, remainingTime(deadline)),
      `Timed out while trying to ${step}`
    );

    if (!Array.isArray(injectionResults) || injectionResults.length === 0) {
      throw new Error("No result was returned from the page");
    }
    return injectionResults[0].result;
  } catch (err) {
    throw explainScriptError(err, step);
  }
}

function explainScriptError(err, step) {
  const detail = err && err.message ? err.message : String(err);
  if (/Cannot access|extensions gallery|chrome:|edge:|about:|file:/i.test(detail)) {
    return new Error(
      `Cannot ${step}. This is a restricted page for Chrome extensions. ` +
        "Please open a normal http:// or https:// page and try again."
    );
  }
  if (/No tab with id|tab was closed|Receiving end does not exist/i.test(detail)) {
    return new Error(`Cannot ${step} because the tab was closed or navigated during capture.`);
  }
  return new Error(`Cannot ${step}: ${detail}`);
}

// ------------------------------------------------------------------
// Capture visible viewport only
// ------------------------------------------------------------------
async function handleCaptureVisible() {
  const deadline = Date.now() + CAPTURE_TIMEOUT_MS;
  try {
    setButtons(false);
    resetProgress();
    setProgress(10, "Preparing...");
    setStatus("Capturing visible area...");

    const tab = await getActiveTab();
    validateCapturableTab(tab);
    const originalUrl = tab.url;

    setProgress(40, "Capturing viewport...");
    const dataURL = await captureVisibleTab(tab.windowId, deadline);
    await ensureSameTab(tab.id, originalUrl, deadline);

    setProgress(75, "Preparing download...");
    setStatus("Downloading...");
    const blob = await dataURLtoBlob(dataURL);
    await downloadBlob(blob, buildFilename(tab.url));

    setProgress(100, "Complete");
    setStatus("Done! Saved to Downloads.", "success");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
  } finally {
    setButtons(true);
  }
}

// ------------------------------------------------------------------
// Capture full page by scrolling + incremental stitching
// ------------------------------------------------------------------
async function handleCaptureFullPage() {
  const deadline = Date.now() + CAPTURE_TIMEOUT_MS;
  let tab;
  let dims;
  let preparedPage = false;

  try {
    setButtons(false);
    resetProgress();
    setProgress(1, "Preparing...");

    tab = await getActiveTab();
    validateCapturableTab(tab);
    const originalUrl = tab.url;

    // 1. Inject script to get page dimensions, page DPR, and disable
    // scroll-snap/smooth scrolling so requested positions are repeatable.
    setStatus("Measuring page...");
    dims = await runScript(
      tab.id,
      (styleId) => {
        let style = document.getElementById(styleId);
        if (!style) {
          style = document.createElement("style");
          style.id = styleId;
          style.textContent = `
            html, body, * {
              scroll-behavior: auto !important;
              scroll-snap-type: none !important;
            }
          `;
          document.documentElement.appendChild(style);
        }

        const scrollHeight = Math.max(
          document.documentElement.scrollHeight,
          document.body ? document.body.scrollHeight : 0
        );
        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;
        const originalScrollY = window.scrollY;
        const devicePixelRatio = window.devicePixelRatio || 1;
        return { scrollHeight, viewportHeight, viewportWidth, originalScrollY, devicePixelRatio };
      },
      [CAPTURE_STYLE_ID],
      "measure this page",
      deadline
    );
    preparedPage = true;

    if (!dims || !dims.viewportHeight || !dims.viewportWidth || !dims.scrollHeight) {
      throw new Error("Could not determine page dimensions");
    }

    const { viewportHeight, viewportWidth, devicePixelRatio } = dims;
    let currentScrollHeight = dims.scrollHeight;
    let estimatedTotal = Math.max(1, Math.ceil(currentScrollHeight / viewportHeight));
    const stitcher = new CaptureStitcher(viewportWidth, currentScrollHeight, devicePixelRatio || 1);

    setStatus(`Page: ${currentScrollHeight}px, ~${estimatedTotal} chunks`);
    setProgress(3, `0/${estimatedTotal} chunks`);
    await sleepWithDeadline(200, deadline);

    // 2. Scroll to top
    await ensureSameTab(tab.id, originalUrl, deadline);
    await runScript(tab.id, (y) => window.scrollTo(0, y), [0], "scroll to the top", deadline);
    await sleepWithDeadline(300, deadline);

    // 3. Capture each viewport chunk and draw it immediately to avoid
    // retaining every screenshot dataURL for very long pages.
    let requestedScrollY = 0;
    let chunkIndex = 0;
    while (requestedScrollY < currentScrollHeight) {
      assertNotTimedOut(deadline);
      await ensureSameTab(tab.id, originalUrl, deadline);

      const maxScrollY = Math.max(0, currentScrollHeight - viewportHeight);
      const targetScrollY = Math.min(requestedScrollY, maxScrollY);
      const actualScrollY = await runScript(
        tab.id,
        async (y) => {
          window.scrollTo(0, y);
          await new Promise((resolve) => requestAnimationFrame(() => resolve()));
          return window.scrollY;
        },
        [targetScrollY],
        "scroll this page",
        deadline
      );

      estimatedTotal = Math.max(1, Math.ceil(currentScrollHeight / viewportHeight));
      setStatus(`Scrolling ${chunkIndex + 1}/${estimatedTotal}...`);
      setProgress((chunkIndex / estimatedTotal) * 85 + 5, `${chunkIndex}/${estimatedTotal} chunks`);
      await sleepWithDeadline(CAPTURE_DELAY_MS, deadline);

      // Re-measure scrollHeight (page may have grown due to lazy loading).
      const newHeight = await runScript(
        tab.id,
        () =>
          Math.max(
            document.documentElement.scrollHeight,
            document.body ? document.body.scrollHeight : 0
          ),
        [],
        "re-measure this page",
        deadline
      );
      if (newHeight > currentScrollHeight) {
        currentScrollHeight = newHeight;
        stitcher.ensureHeight(currentScrollHeight);
      }

      // Capture current viewport.
      estimatedTotal = Math.max(1, Math.ceil(currentScrollHeight / viewportHeight));
      setStatus(`Capturing ${chunkIndex + 1}/${estimatedTotal}...`);
      const dataURL = await captureVisibleTab(tab.windowId, deadline);
      await ensureSameTab(tab.id, originalUrl, deadline);
      await stitcher.drawCapture(dataURL, actualScrollY, viewportHeight, currentScrollHeight);

      chunkIndex++;
      setProgress(
        Math.min(90, (chunkIndex / estimatedTotal) * 85 + 5),
        `${Math.min(chunkIndex, estimatedTotal)}/${estimatedTotal} chunks`
      );

      requestedScrollY += viewportHeight;
    }

    // 4. Stitching is already incremental; just encode the final canvas.
    setStatus("Encoding PNG...");
    setProgress(93, "Encoding PNG...");
    await sleepWithDeadline(100, deadline);
    const stitchedBlob = await stitcher.toBlob();

    // 5. Download.
    await ensureSameTab(tab.id, originalUrl, deadline);
    setStatus("Downloading...");
    setProgress(97, "Downloading...");
    await downloadBlob(stitchedBlob, buildFilename(tab.url));
    setProgress(100, "Complete");
    setStatus(`Done! ${chunkIndex} chunks stitched.\nSaved to Downloads.`, "success");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
  } finally {
    if (preparedPage && tab && typeof tab.id === "number" && dims) {
      try {
        await runScript(
          tab.id,
          (styleId, y) => {
            const style = document.getElementById(styleId);
            if (style) style.remove();
            window.scrollTo(0, y);
          },
          [CAPTURE_STYLE_ID, dims.originalScrollY || 0],
          "restore this page",
          Date.now() + SCRIPT_TIMEOUT_MS
        );
      } catch (_) {
        // The tab may have been closed/navigated; the user-facing error above is enough.
      }
    }
    setButtons(true);
  }
}

// ------------------------------------------------------------------
// Stitch captured viewport images into a single tall PNG
// ------------------------------------------------------------------
class CaptureStitcher {
  constructor(viewportWidth, scrollHeight, dpr) {
    this.viewportWidth = viewportWidth;
    this.dpr = dpr || 1;
    this.width = Math.round(viewportWidth * this.dpr);
    this.height = Math.max(1, Math.round(scrollHeight * this.dpr));
    validateCanvasSize(this.width, this.height);
    this.canvas = createCanvas(this.width, this.height);
    this.ctx = this.canvas.getContext("2d");
    if (!this.ctx) {
      throw new Error("Could not create a canvas context for stitching");
    }
  }

  ensureHeight(scrollHeight) {
    const newHeight = Math.max(1, Math.round(scrollHeight * this.dpr));
    if (newHeight <= this.height) return;

    validateCanvasSize(this.width, newHeight);
    const oldCanvas = this.canvas;
    const newCanvas = createCanvas(this.width, newHeight);
    const newCtx = newCanvas.getContext("2d");
    if (!newCtx) {
      throw new Error("Could not grow the stitching canvas");
    }
    newCtx.drawImage(oldCanvas, 0, 0);
    this.canvas = newCanvas;
    this.ctx = newCtx;
    this.height = newHeight;
  }

  async drawCapture(dataURL, scrollY, viewportHeight, scrollHeight) {
    this.ensureHeight(scrollHeight);
    const decoded = await decodeCapture(dataURL);
    try {
      const destY = Math.round(scrollY * this.dpr);
      const remaining = this.height - destY;
      if (remaining <= 0) return;

      const sourceWidth = Math.min(decoded.width, this.width);
      const sourceHeight = Math.min(
        decoded.height,
        Math.round(viewportHeight * this.dpr),
        remaining
      );

      if (sourceWidth <= 0 || sourceHeight <= 0) return;

      this.ctx.drawImage(
        decoded.image,
        0,
        0,
        sourceWidth,
        sourceHeight,
        0,
        destY,
        sourceWidth,
        sourceHeight
      );
    } finally {
      decoded.close();
    }
  }

  toBlob() {
    return canvasToBlob(this.canvas, "image/png");
  }
}

function createCanvas(width, height) {
  if (typeof OffscreenCanvas !== "undefined") {
    return new OffscreenCanvas(width, height);
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function validateCanvasSize(width, height) {
  if (
    width > MAX_CANVAS_DIMENSION ||
    height > MAX_CANVAS_DIMENSION ||
    width * height > MAX_CANVAS_PIXELS
  ) {
    throw new Error(
      "The final screenshot is too large for the browser canvas limit. " +
        "Try zooming out, reducing page height, or capturing in smaller sections."
    );
  }
}

async function decodeCapture(dataURL) {
  const blob = await dataURLtoBlob(dataURL);
  if (typeof createImageBitmap === "function") {
    const image = await createImageBitmap(blob);
    return {
      image,
      width: image.width,
      height: image.height,
      close: () => image.close && image.close(),
    };
  }

  const objectURL = URL.createObjectURL(blob);
  try {
    const image = await loadImage(objectURL);
    return {
      image,
      width: image.width,
      height: image.height,
      close: () => URL.revokeObjectURL(objectURL),
    };
  } catch (err) {
    URL.revokeObjectURL(objectURL);
    throw err;
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load captured image"));
    img.src = src;
  });
}

function canvasToBlob(canvas, type) {
  if (typeof canvas.convertToBlob === "function") {
    return canvas.convertToBlob({ type });
  }

  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error("Failed to encode stitched image"));
      }
    }, type);
  });
}

// ------------------------------------------------------------------
// UI helpers
// ------------------------------------------------------------------
function setButtons(enabled) {
  fullPageBtn.disabled = !enabled;
  visibleBtn.disabled = !enabled;
}

fullPageBtn.addEventListener("click", handleCaptureFullPage);
visibleBtn.addEventListener("click", handleCaptureVisible);
