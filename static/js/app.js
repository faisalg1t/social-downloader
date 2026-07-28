(() => {
  const $ = (id) => document.getElementById(id);

  const form = $("intakeForm");
  const urlInput = $("urlInput");
  const pasteBtn = $("pasteBtn");
  const fetchBtn = $("fetchBtn");
  const statusArea = $("statusArea");
  const statusText = $("statusText");
  const errorArea = $("errorArea");
  const resultArea = $("resultArea");
  const progressArea = $("progressArea");
  const themeToggle = $("themeToggle");

  const STORAGE_THEME_KEY = "omnigrab-theme";
  const savedTheme = localStorage.getItem(STORAGE_THEME_KEY);
  if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);

  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    const next = current === "light" ? "dark" : "light";
    if (next === "dark") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
    }
    localStorage.setItem(STORAGE_THEME_KEY, next);
  });

  pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) urlInput.value = text.trim();
    } catch {
      urlInput.focus();
    }
  });

  function showError(message) {
    errorArea.textContent = message;
    errorArea.hidden = false;
  }
  function hideError() { errorArea.hidden = true; }

  function humanSize(bytes) {
    if (!bytes) return "";
    const units = ["B", "KB", "MB", "GB"];
    let v = bytes, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(1)}${units[i]}`;
  }

  function humanDuration(seconds) {
    if (!seconds) return "";
    const s = Math.floor(seconds % 60).toString().padStart(2, "0");
    const m = Math.floor((seconds / 60) % 60).toString().padStart(2, "0");
    const h = Math.floor(seconds / 3600);
    return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
  }

  function buildStub(fmt, mediaUrl, mediaTitle) {
    const btn = document.createElement("button");
    btn.className = "stub" + (fmt.kind === "audio" ? " audio" : "");
    btn.type = "button";

    const res = document.createElement("span");
    res.className = "stub-res";
    res.textContent = fmt.kind === "audio" ? (fmt.note || "Audio") : (fmt.resolution || fmt.note || "Unknown");
    btn.appendChild(res);

    const detailParts = [fmt.ext?.toUpperCase()];
    if (fmt.vcodec && fmt.vcodec !== "none") detailParts.push(fmt.vcodec.split(".")[0]);
    if (fmt.acodec && fmt.acodec !== "none" && fmt.kind !== "video") detailParts.push(fmt.acodec.split(".")[0]);
    if (fmt.filesize) detailParts.push(humanSize(fmt.filesize));
    const detail = document.createElement("span");
    detail.className = "stub-detail";
    detail.textContent = detailParts.filter(Boolean).join(" · ");
    btn.appendChild(detail);

    btn.addEventListener("click", () => beginDownload(mediaUrl, fmt, mediaTitle, btn));
    return btn;
  }

  async function fetchInfo(url) {
    hideError();
    resultArea.hidden = true;
    progressArea.hidden = true;
    statusArea.hidden = false;
    statusText.textContent = "Reading the manifest…";
    fetchBtn.disabled = true;

    try {
      const res = await fetch("/api/info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.detail || "Could not read that link.");
        return;
      }
      renderResult(data, url);
    } catch (err) {
      showError("Network error while contacting the server. Please try again.");
    } finally {
      statusArea.hidden = true;
      fetchBtn.disabled = false;
    }
  }

  function renderResult(info, originalUrl) {
    $("thumb").src = info.thumbnail || "";
    $("thumb").alt = info.title || "";
    $("mediaTitle").textContent = info.title;
    $("sourceTag").textContent = (info.extractor || "SOURCE").toUpperCase();
    $("uploader").textContent = info.uploader ? `by ${info.uploader}` : "";
    $("duration").textContent = info.duration ? humanDuration(info.duration) : "";

    const videoBox = $("videoFormats");
    const audioBox = $("audioFormats");
    const videoOnlyBox = $("videoOnlyFormats");
    videoBox.innerHTML = "";
    audioBox.innerHTML = "";
    videoOnlyBox.innerHTML = "";

    for (const fmt of info.formats) {
      const stub = buildStub(fmt, info.webpage_url || originalUrl, info.title);
      if (fmt.kind === "video") videoBox.appendChild(stub);
      else if (fmt.kind === "audio") audioBox.appendChild(stub);
      else videoOnlyBox.appendChild(stub);
    }

    resultArea.hidden = false;
  }

  async function beginDownload(url, fmt, title, stubEl) {
    hideError();
    progressArea.hidden = false;
    $("downloadLink").hidden = true;
    $("progressLabel").textContent = "Queuing download…";
    $("progressPercent").textContent = "0%";
    $("progressBar").style.width = "0%";
    $("progressSpeed").textContent = "";
    $("progressEta").textContent = "";
    progressArea.scrollIntoView({ behavior: "smooth", block: "nearest" });

    document.querySelectorAll(".stub").forEach((b) => (b.disabled = true));

    try {
      const res = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, format_id: fmt.format_id, audio_only: fmt.kind === "audio" }),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.detail || "Could not start the download.");
        resetStubs();
        return;
      }
      pollStatus(data.task_id);
    } catch {
      showError("Network error while starting the download.");
      resetStubs();
    }
  }

  function resetStubs() {
    document.querySelectorAll(".stub").forEach((b) => (b.disabled = false));
  }

  async function pollStatus(taskId) {
    const poll = async () => {
      try {
        const res = await fetch(`/api/status/${taskId}`);
        const data = await res.json();

        if (data.status === "error") {
          showError(data.error || "The download failed.");
          progressArea.hidden = true;
          resetStubs();
          return;
        }

        if (data.status === "downloading") {
          $("progressLabel").textContent = "Downloading…";
          $("progressPercent").textContent = `${data.percent}%`;
          $("progressBar").style.width = `${data.percent}%`;
          $("progressSpeed").textContent = data.speed ? `${data.speed}` : "";
          $("progressEta").textContent = data.eta ? `ETA ${data.eta}` : "";
        } else if (data.status === "processing") {
          $("progressLabel").textContent = "Finalizing file…";
          $("progressPercent").textContent = "99%";
          $("progressBar").style.width = "99%";
        } else if (data.status === "finished") {
          $("progressLabel").textContent = "Ready";
          $("progressPercent").textContent = "100%";
          $("progressBar").style.width = "100%";
          const link = $("downloadLink");
          link.href = `/api/file/${taskId}`;
          link.hidden = false;
          link.textContent = `Save ${data.filename || "file"}`;
          link.setAttribute("download", data.filename || "download");
          resetStubs();
          return;
        }
        setTimeout(poll, 900);
      } catch {
        setTimeout(poll, 1500);
      }
    };
    poll();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!url) return;
    fetchInfo(url);
  });
})();
