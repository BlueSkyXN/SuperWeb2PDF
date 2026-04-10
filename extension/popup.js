/* global chrome */

const statusEl = document.getElementById("status");
const fullPageBtn = document.getElementById("captureFullPage");
const visibleBtn = document.getElementById("captureVisible");

function setStatus(msg, level) {
  statusEl.textContent = msg;
  statusEl.className = level || "";
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
  return `s2p-${hostname}-${timestamp()}.png`;
}

function dataURLtoBlob(dataURL) {
  const [header, b64] = dataURL.split(",");
  const mime = header.match(/:(.*?);/)[1];
  const bytes = atob(b64);
  const buf = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
  return new Blob([buf], { type: mime });
}

function downloadBlob(blob, filename) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      chrome.downloads.download(
        { url: reader.result, filename, saveAs: false },
        (downloadId) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(downloadId);
          }
        }
      );
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function captureVisibleTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(null, { format: "png" }, (dataURL) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(dataURL);
      }
    });
  });
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

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ------------------------------------------------------------------
// Capture visible viewport only
// ------------------------------------------------------------------
async function handleCaptureVisible() {
  try {
    setButtons(false);
    setStatus("Capturing visible area...");
    const tab = await getActiveTab();
    const dataURL = await captureVisibleTab();
    setStatus("Downloading...");
    const blob = dataURLtoBlob(dataURL);
    await downloadBlob(blob, buildFilename(tab.url));
    setStatus("Done! Saved to Downloads.", "success");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
  } finally {
    setButtons(true);
  }
}

// ------------------------------------------------------------------
// Capture full page by scrolling + stitching
// ------------------------------------------------------------------
async function handleCaptureFullPage() {
  try {
    setButtons(false);
    const tab = await getActiveTab();

    // 1. Inject script to get page dimensions and prepare for scrolling
    setStatus("Measuring page...");
    const [{ result: dims }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const scrollHeight = Math.max(
          document.documentElement.scrollHeight,
          document.body.scrollHeight
        );
        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;
        const originalScrollY = window.scrollY;
        return { scrollHeight, viewportHeight, viewportWidth, originalScrollY };
      },
    });

    const { scrollHeight, viewportHeight, viewportWidth } = dims;
    const totalChunks = Math.ceil(scrollHeight / viewportHeight);

    setStatus(`Page: ${scrollHeight}px, ${totalChunks} chunks`);
    await sleep(200);

    // 2. Scroll to top
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.scrollTo(0, 0),
    });
    await sleep(300);

    // 3. Capture each viewport chunk
    const captures = [];

    for (let i = 0; i < totalChunks; i++) {
      const scrollY = i * viewportHeight;

      // Scroll to position
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (y) => window.scrollTo(0, y),
        args: [scrollY],
      });

      // Wait for lazy-loaded content
      setStatus(`Scrolling ${i + 1}/${totalChunks}...`);
      await sleep(500);

      // Capture current viewport
      setStatus(`Capturing ${i + 1}/${totalChunks}...`);
      const dataURL = await captureVisibleTab();
      captures.push({ dataURL, scrollY });
    }

    // 4. Scroll back to top
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (y) => window.scrollTo(0, y),
      args: [dims.originalScrollY],
    });

    // 5. Stitch captures into one image
    setStatus("Stitching...");
    await sleep(100);

    const stitchedBlob = await stitchCaptures(
      captures,
      viewportWidth,
      viewportHeight,
      scrollHeight,
      window.devicePixelRatio || 1
    );

    // 6. Download
    setStatus("Downloading...");
    await downloadBlob(stitchedBlob, buildFilename(tab.url));
    setStatus(`Done! ${totalChunks} chunks stitched.\nSaved to Downloads.`, "success");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
  } finally {
    setButtons(true);
  }
}

// ------------------------------------------------------------------
// Stitch captured viewport images into a single tall PNG
// ------------------------------------------------------------------
async function stitchCaptures(
  captures,
  viewportWidth,
  viewportHeight,
  scrollHeight,
  dpr
) {
  // captureVisibleTab respects device pixel ratio, so images are dpr × larger
  const imgWidth = Math.round(viewportWidth * dpr);
  const imgChunkHeight = Math.round(viewportHeight * dpr);
  const totalHeight = Math.round(scrollHeight * dpr);

  const canvas = new OffscreenCanvas(imgWidth, totalHeight);
  const ctx = canvas.getContext("2d");

  for (let i = 0; i < captures.length; i++) {
    const { dataURL, scrollY } = captures[i];
    const img = await loadImage(dataURL);

    const destY = Math.round(scrollY * dpr);
    const remaining = totalHeight - destY;
    const drawHeight = Math.min(img.height, remaining);

    // For the last chunk, only draw the portion that maps to real content
    ctx.drawImage(
      img,
      0, 0, img.width, drawHeight,   // source rect
      0, destY, img.width, drawHeight // dest rect
    );
  }

  return await canvas.convertToBlob({ type: "image/png" });
}

function loadImage(dataURL) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load captured image"));
    img.src = dataURL;
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
