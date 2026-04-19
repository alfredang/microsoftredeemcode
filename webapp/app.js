const SG_SUFFIX = "?WT.mc_id=ilt_partner_webpage_wwl&ocid=5238477";
const MAX_VISIBLE = 50;
const DEBOUNCE_MS = 120;
const GITHUB_REPO = "alfredang/microsoftredeemcode";
const RAW_BASE = "https://raw.githubusercontent.com/alfredang/microsoftredeemcode/main/webapp";
const WORKER_URL = "https://msredeem-dispatch.angch.workers.dev";
const POLL_INTERVAL = 5000;
const POLL_TIMEOUT = 180000;

const $q = document.getElementById("q");
const $results = document.getElementById("results");
const $status = document.getElementById("status");
const template = document.getElementById("card-template");

let courses = [];
let debounceId = 0;
let backendAvailable = false;

localStorage.removeItem("gh_pat");

function singaporeUrl(baseUrl) {
  return baseUrl + SG_SUFFIX;
}

function tokenize(query) {
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean);
}

function filterCourses(query) {
  const tokens = tokenize(query);
  if (tokens.length === 0) return courses;
  return courses.filter((c) => {
    const haystack = (c.courseNumber + " " + c.title).toLowerCase();
    return tokens.every((t) => haystack.includes(t));
  });
}

function renderCard(course) {
  const node = template.content.firstElementChild.cloneNode(true);
  node.querySelector(".course-number").textContent = course.courseNumber;
  node.querySelector(".area").textContent = course.solutionArea || "";
  node.querySelector(".title").textContent = course.title;
  node.querySelector(".duration").textContent = course.duration || "";
  node.querySelector(".credential").textContent = course.credential || "";

  const url = singaporeUrl(course.baseUrl);
  const openLink = node.querySelector(".open-link");
  openLink.href = url;

  const copyBtn = node.querySelector(".copy-link");
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(url);
      const original = copyBtn.textContent;
      copyBtn.textContent = "Copied!";
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyBtn.textContent = original;
        copyBtn.classList.remove("copied");
      }, 1400);
    } catch {
      window.prompt("Copy this Singapore link:", url);
    }
  });

  const genBtn = node.querySelector(".gen-btn");
  const genStudents = node.querySelector(".gen-students");
  const genStatus = node.querySelector(".gen-status");
  const codeList = node.querySelector(".code-list");
  const stepperMinus = node.querySelector(".stepper-minus");
  const stepperPlus = node.querySelector(".stepper-plus");

  const clampStepper = () => {
    const n = Math.max(1, Math.min(1000, parseInt(genStudents.value, 10) || 1));
    genStudents.value = n;
    stepperMinus.disabled = n <= 1;
    stepperPlus.disabled = n >= 1000;
  };
  stepperMinus.addEventListener("click", () => {
    genStudents.value = Math.max(1, (parseInt(genStudents.value, 10) || 1) - 1);
    clampStepper();
  });
  stepperPlus.addEventListener("click", () => {
    genStudents.value = Math.min(1000, (parseInt(genStudents.value, 10) || 1) + 1);
    clampStepper();
  });
  genStudents.addEventListener("input", clampStepper);
  clampStepper();

  genBtn.addEventListener("click", () =>
    handleGenerate({ course, genBtn, genStudents, genStatus, codeList }),
  );

  return node;
}

async function handleGenerate({ course, genBtn, genStudents, genStatus, codeList }) {
  const students = Math.max(1, Math.min(1000, parseInt(genStudents.value, 10) || 1));

  // Use local backend if available, otherwise use GitHub Actions
  if (backendAvailable) {
    await handleGenerateLocal({ course, genBtn, genStudents, genStatus, codeList, students });
  } else {
    await handleGenerateGitHub({ course, genBtn, genStatus, codeList, students });
  }
}

async function handleGenerateLocal({ course, genBtn, genStudents, genStatus, codeList, students }) {
  genBtn.disabled = true;
  const originalLabel = genBtn.textContent;
  genBtn.textContent = "Generating…";

  const loggedIn = await ensureSignedIn(genStatus);
  if (!loggedIn) {
    genBtn.disabled = false;
    genBtn.textContent = originalLabel;
    return;
  }

  setStatus(
    genStatus,
    `Requesting an achievement code for ${students} student${students === 1 ? "" : "s"}…`,
  );
  codeList.hidden = true;
  codeList.replaceChildren();

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ courseNumber: course.courseNumber, count: 1, students }),
    });
    const data = await res.json();

    if (data.results && data.results.length) {
      renderResults(codeList, data.results);
    } else if (data.codes && data.codes.length) {
      renderResults(codeList, data.codes.map((c) => ({ code: c, url: "" })));
    }

    if (data.ok) {
      setStatus(genStatus, `Code generated for ${students} students. Saved to codes.csv.`, "ok");
    } else {
      const msg = (data.errors && data.errors.join(" · ")) || data.error || "Unknown error";
      setStatus(genStatus, msg, "err");
    }
  } catch (err) {
    setStatus(genStatus, `Request failed: ${err.message}`, "err");
  } finally {
    genBtn.disabled = false;
    genBtn.textContent = originalLabel;
  }
}

async function handleGenerateGitHub({ course, genBtn, genStatus, codeList, students }) {
  const requestId = crypto.randomUUID();
  genBtn.disabled = true;
  const originalLabel = genBtn.textContent;
  codeList.hidden = true;
  codeList.replaceChildren();

  setStatus(genStatus, "Triggering GitHub Actions workflow…");
  genBtn.textContent = "Triggering…";
  try {
    const res = await fetch(WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: "generate-code",
        client_payload: {
          courseNumber: course.courseNumber,
          courseUrl: course.baseUrl,
          students: String(students),
          requestId,
        },
      }),
    });
    if (!res.ok) {
      const msg = await res.text();
      throw new Error(`Proxy ${res.status}: ${msg}`);
    }
  } catch (err) {
    setStatus(genStatus, `Failed to trigger workflow: ${err.message}`, "err");
    genBtn.disabled = false;
    genBtn.textContent = originalLabel;
    return;
  }

  // Poll for result
  setStatus(genStatus, "Workflow triggered. Waiting for result (~60-90s)…");
  genBtn.textContent = "Waiting…";
  const resultUrl = `${RAW_BASE}/results/${requestId}.json`;
  const deadline = Date.now() + POLL_TIMEOUT;
  let dotCount = 0;

  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL));
    dotCount++;
    const dots = ".".repeat((dotCount % 3) + 1);
    genBtn.textContent = `Waiting${dots}`;
    setStatus(
      genStatus,
      `Waiting for GitHub Actions result${dots} (${Math.round((Date.now() - (deadline - POLL_TIMEOUT)) / 1000)}s)`,
    );

    try {
      const res = await fetch(resultUrl, { cache: "no-store" });
      if (res.status === 200) {
        const data = await res.json();
        if (data.ok) {
          renderResults(codeList, [{ code: data.code, url: data.url || "" }]);
          setStatus(genStatus, `Code generated for ${students} students via GitHub Actions.`, "ok");
        } else {
          setStatus(genStatus, `Generation failed: ${data.error}`, "err");
        }
        genBtn.disabled = false;
        genBtn.textContent = originalLabel;
        return;
      }
    } catch {
      // Result not ready yet
    }
  }

  setStatus(
    genStatus,
    "Timed out waiting for result. Check https://github.com/" + GITHUB_REPO + "/actions for the workflow status.",
    "err",
  );
  genBtn.disabled = false;
  genBtn.textContent = originalLabel;
}

function setStatus(el, text, level) {
  el.textContent = text;
  el.classList.remove("ok", "err");
  if (level) el.classList.add(level);
  el.hidden = false;
}

function renderResults(listEl, results) {
  const frag = document.createDocumentFragment();
  for (const { code, url } of results) {
    const li = document.createElement("li");
    li.classList.add("code-item");

    const codeSpan = document.createElement("span");
    codeSpan.className = "code-value";
    codeSpan.textContent = code;
    li.appendChild(codeSpan);

    li.appendChild(makeCopyButton(code, "Copy code"));

    if (url) {
      const urlLink = document.createElement("a");
      urlLink.className = "code-url";
      urlLink.href = url;
      urlLink.target = "_blank";
      urlLink.rel = "noopener";
      urlLink.textContent = url;
      li.appendChild(urlLink);
      li.appendChild(makeCopyButton(url, "Copy URL"));
    }

    frag.appendChild(li);
  }
  listEl.replaceChildren(frag);
  listEl.hidden = false;
}

function makeCopyButton(value, label) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-ghost copy-code";
  btn.textContent = label;
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(value);
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = orig;
        btn.classList.remove("copied");
      }, 1200);
    } catch {
      window.prompt("Copy:", value);
    }
  });
  return btn;
}

function renderEmpty(message, hint) {
  const el = document.createElement("div");
  el.className = "empty";
  const strong = document.createElement("strong");
  strong.textContent = message;
  el.appendChild(strong);
  if (hint) {
    const p = document.createElement("div");
    p.textContent = hint;
    el.appendChild(p);
  }
  return el;
}

function render(query) {
  $results.replaceChildren();

  const matches = filterCourses(query);
  const total = courses.length;

  if (!query.trim()) {
    $status.textContent = `${total} Microsoft courses loaded`;
    $results.appendChild(
      renderEmpty(
        "Start typing to find a course",
        "Search by course number (AI-102) or any words in the title.",
      ),
    );
    return;
  }

  if (matches.length === 0) {
    $status.textContent = `No matches for “${query}”`;
    $results.appendChild(
      renderEmpty("No matching course", "Try a shorter query or a course number like MS-900."),
    );
    return;
  }

  const visible = matches.slice(0, MAX_VISIBLE);
  $status.textContent =
    matches.length > MAX_VISIBLE
      ? `Showing ${visible.length} of ${matches.length} matches`
      : `Showing ${visible.length} of ${total}`;

  const frag = document.createDocumentFragment();
  for (const c of visible) frag.appendChild(renderCard(c));
  $results.appendChild(frag);

  if (matches.length > MAX_VISIBLE) {
    const more = document.createElement("div");
    more.className = "empty";
    more.textContent = `…and ${matches.length - MAX_VISIBLE} more. Refine your search.`;
    $results.appendChild(more);
  }
}

function onInput() {
  clearTimeout(debounceId);
  debounceId = setTimeout(() => render($q.value), DEBOUNCE_MS);
}

async function checkBackend() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    backendAvailable = true;
  } catch {
    backendAvailable = false;
  }
}

async function ensureSignedIn(genStatus) {
  const res = await fetch("/api/status");
  const data = await res.json();
  if (data.signedIn) return true;

  setStatus(genStatus, "Signing in to Microsoft Learn…");
  const loginRes = await fetch("/api/login", { method: "POST" });
  const loginData = await loginRes.json();
  if (!loginData.ok) {
    setStatus(genStatus, `Auto sign-in failed: ${loginData.error}`, "err");
    return false;
  }
  return true;
}

async function boot() {
  $status.textContent = "Loading courses…";
  try {
    const res = await fetch("courses.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    courses = await res.json();
  } catch (err) {
    $status.textContent = "";
    $results.replaceChildren(
      renderEmpty(
        "Could not load courses.json",
        "Start the backend: `python server.py` and open http://localhost:8000.",
      ),
    );
    console.error(err);
    return;
  }
  $q.addEventListener("input", onInput);
  render("");
  checkBackend();
}

boot();
