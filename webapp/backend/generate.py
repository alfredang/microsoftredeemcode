"""Drive Microsoft Learn with Playwright to request achievement codes.

Flow per code:
  1. Click "Request achievement code" on the course page (opens a modal).
  2. In the modal, fill the "students redeeming this code" input.
  3. Click "Request code" inside the modal.
  4. Read the generated code + URL from the success state of the modal.
  5. Close the modal before the next iteration.
"""

import csv
import re
import time
from datetime import datetime, timezone

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .paths import CODES_CSV, DEBUG_DIR, SG_SUFFIX, STORAGE_STATE

# Voucher codes on MS Learn can be short (e.g. "8X582M" = 6 chars). Accept any
# 5+ char alphanumeric token (with optional dashes) and exclude obvious words.
CODE_RE = re.compile(r"[A-Z0-9]{5,}(?:-[A-Z0-9]{3,}){0,4}")
URL_RE = re.compile(r"https?://[^\s\"']+")

OPEN_MODAL_BUTTON = re.compile(r"^\s*Request achievement code\s*$", re.IGNORECASE)
SUBMIT_BUTTON = re.compile(r"^\s*Request code\s*$", re.IGNORECASE)
READY_TEXT = re.compile(r"code is ready", re.IGNORECASE)

HEADLESS = True
VIEWPORT = {"width": 1280, "height": 860}

CODE_BLOCKLIST = {
    "ACHIEVEMENT",
    "REQUEST",
    "MICROSOFT",
    "STUDENT",
    "STUDENTS",
    "REDEEM",
    "LEARN",
    "CODE",
    "COPY",
    "CLOSE",
}


# -----------------------------------------------------------------------------
# Page-level helpers
# -----------------------------------------------------------------------------


class StepError(RuntimeError):
    """A Playwright step failed in a recognisable way."""

    def __init__(self, step: str, message: str):
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message


def _scroll_through_page(page) -> None:
    """Scroll the page top-to-bottom to force any lazy-loaded sections to render."""
    try:
        page.evaluate(
            """
            async () => {
              const h = document.body.scrollHeight;
              for (let y = 0; y <= h; y += Math.max(300, window.innerHeight - 100)) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
              }
              window.scrollTo(0, 0);
            }
            """
        )
    except Exception:
        pass


def _find_request_button_anywhere(page, timeout_ms: int = 30000):
    """Step 1: search the whole page (including iframes) for the Request
    achievement code button. Returns (locator, frame) or raises StepError."""
    patterns = [
        re.compile(r"^\s*Request achievement code\s*$", re.IGNORECASE),
        re.compile(r"Request achievement code", re.IGNORECASE),
        re.compile(r"Request a code", re.IGNORECASE),
        re.compile(r"Get achievement code", re.IGNORECASE),
    ]

    deadline = time.time() + timeout_ms / 1000
    last_err = None
    scrolled_once = False

    while time.time() < deadline:
        frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]

        for frame in frames:
            for pat in patterns:
                # Strategy A: accessible-role lookup.
                try:
                    loc = frame.get_by_role("button", name=pat).first
                    if loc.count() and loc.is_visible():
                        return loc, frame
                except Exception as err:
                    last_err = err

                # Strategy B: any clickable element with matching text.
                try:
                    loc = (
                        frame.locator("button, a, [role=button], [role=link]")
                        .filter(has_text=pat)
                        .first
                    )
                    if loc.count() and loc.is_visible():
                        return loc, frame
                except Exception as err:
                    last_err = err

                # Strategy C: plain text anchor whose nearest clickable ancestor is the target.
                try:
                    loc = frame.get_by_text(pat).first
                    if loc.count() and loc.is_visible():
                        return loc, frame
                except Exception as err:
                    last_err = err

        # On the first pass, force-scroll to trigger lazy loaders once.
        if not scrolled_once:
            _scroll_through_page(page)
            scrolled_once = True

        page.wait_for_timeout(500)

    # Compose a hint so the user knows *why* the button wasn't found.
    hints = []
    try:
        body = page.inner_text("body").lower()
        if "sign in" in body and "sign out" not in body:
            hints.append("the page shows a 'Sign in' prompt — session may have expired")
        if "not available" in body or "no longer available" in body:
            hints.append("the page text says the course is not available")
        if "achievement code" not in body:
            hints.append(
                "'Achievement Code' text is absent on the page — your account may not be entitled to request a code for this course"
            )
    except Exception:
        pass
    hint_str = (" Possible causes: " + "; ".join(hints) + ".") if hints else ""

    raise StepError(
        "Find Request achievement code button",
        f"Button not found anywhere on the page within {timeout_ms // 1000}s "
        f"(searched main frame + {max(0, len(list(page.frames)) - 1)} sub-frames, "
        f"tried role/text/clickable selectors).{hint_str} "
        f"Last playwright error: {last_err}",
    )


def _click_found_button(btn) -> None:
    try:
        btn.scroll_into_view_if_needed()
        btn.click(timeout=5000)
    except Exception as err:
        raise StepError(
            "Click 'Request achievement code'",
            f"Clicking the button failed — {err}",
        )


def _modal(page):
    """Return the currently-open dialog locator (or the best-effort fallback)."""
    for selector in ("[role='dialog']", "[aria-modal='true']", "dialog"):
        loc = page.locator(selector).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return page.locator("body")


def _wait_for_modal(page, timeout_ms: int = 10000) -> None:
    dialog = page.locator("[role='dialog'], [aria-modal='true'], dialog").first
    try:
        dialog.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        raise StepError(
            "Wait for modal",
            f"No dialog appeared within {timeout_ms // 1000}s after clicking 'Request achievement code'.",
        )


def _fill_student_count(page, students: int) -> None:
    """Locate the student-quantity input in the modal and fill it."""
    dialog = _modal(page)
    candidate_selectors = [
        "input[type='number']",
        "input[inputmode='numeric']",
        "[role='spinbutton']",
        "input",
    ]
    last_err = None
    for sel in candidate_selectors:
        try:
            loc = dialog.locator(sel)
            n = loc.count()
        except Exception as err:
            last_err = err
            continue
        for i in range(n):
            el = loc.nth(i)
            try:
                if not el.is_visible() or not el.is_editable():
                    continue
                el.fill(str(students))
                return
            except Exception as err:
                last_err = err
                continue
    raise StepError(
        "Fill student count",
        f"Could not find an editable student-count input inside the modal. "
        f"Underlying: {last_err}",
    )


def _click_submit_in_modal(page) -> None:
    dialog = _modal(page)
    btn = dialog.get_by_role("button", name=SUBMIT_BUTTON).first
    try:
        if not btn.count():
            raise StepError(
                "Submit in modal",
                "'Request code' button is missing inside the modal.",
            )
        btn.wait_for(state="visible", timeout=10000)
    except StepError:
        raise
    except Exception as err:
        raise StepError(
            "Submit in modal",
            f"'Request code' button did not become visible — {err}",
        )

    # Wait for the button to become enabled (disabled until input has a value).
    for _ in range(15):
        try:
            if btn.is_enabled():
                break
        except Exception:
            pass
        page.wait_for_timeout(200)
    else:
        raise StepError(
            "Submit in modal",
            "'Request code' button stayed disabled — the student-count input "
            "may be invalid or required additional fields.",
        )
    try:
        btn.click(timeout=5000)
    except Exception as err:
        raise StepError("Submit in modal", f"Clicking 'Request code' failed — {err}")


def _wait_for_success(page, timeout_ms: int = 30000) -> None:
    dialog = _modal(page)
    deadline = time.time() + timeout_ms / 1000
    last_text = ""
    while time.time() < deadline:
        try:
            last_text = dialog.inner_text()
            if READY_TEXT.search(last_text):
                return
            # Detect obvious error states rendered inside the dialog.
            lower = last_text.lower()
            if "error" in lower or "something went wrong" in lower or "try again" in lower:
                raise StepError(
                    "Wait for success",
                    f"Microsoft returned an error in the modal: "
                    f"{last_text.strip().splitlines()[0][:160]}",
                )
        except StepError:
            raise
        except Exception:
            pass
        page.wait_for_timeout(400)
    raise StepError(
        "Wait for success",
        f"No 'code is ready to share' message within {timeout_ms // 1000}s "
        f"after clicking 'Request code'.",
    )


def _extract_code_and_url(page) -> tuple[str, str]:
    """Prefer anchoring on the Copy-code / Copy-URL buttons — their labels are stable."""
    dialog = _modal(page)

    code = _value_near_button(dialog, re.compile(r"copy\s*code", re.IGNORECASE), "code")
    url = _value_near_button(dialog, re.compile(r"copy\s*url", re.IGNORECASE), "url")

    # Fallback: scan all visible inputs in the dialog and classify them.
    if not code or not url:
        try:
            inputs = dialog.locator("input")
            n = inputs.count()
        except Exception:
            n = 0
        for i in range(n):
            el = inputs.nth(i)
            try:
                if not el.is_visible():
                    continue
                val = (el.input_value() or "").strip()
            except Exception:
                continue
            if not val:
                continue
            if not url and val.lower().startswith(("http://", "https://")):
                url = val
                continue
            if not code and _looks_like_code(val):
                code = val

    # Final fallback: dialog inner_text.
    if not code or not url:
        try:
            text = dialog.inner_text()
        except Exception:
            text = ""
        if not url:
            m = URL_RE.search(text)
            if m:
                url = m.group(0)
        if not code:
            for cand in _candidate_codes(text):
                if cand.lower() not in url.lower() if url else True:
                    code = cand
                    break

    if not code and not url:
        raise StepError(
            "Extract code + URL",
            "Success message appeared but neither a code nor a URL was found in the modal.",
        )
    if not code:
        raise StepError(
            "Extract code + URL",
            f"Found URL ({url}) but could not locate the code value near the 'Copy code' button.",
        )
    if not url:
        # Not fatal — some flows only show a code. Log and continue.
        pass
    return code, url


def _value_near_button(dialog, name_re, kind: str) -> str:
    """Find a button matching name_re, then read the value of the input/field
    next to it (same row / adjacent container). kind='url'|'code'."""
    try:
        btns = dialog.get_by_role("button", name=name_re)
        n = btns.count()
    except Exception:
        return ""

    for i in range(n):
        btn = btns.nth(i)
        try:
            if not btn.is_visible():
                continue
        except Exception:
            continue

        # Walk up to 4 ancestors; at each level, look for an input whose value
        # matches the expected shape, then for any text-bearing element.
        for up in range(1, 5):
            container = btn.locator(f"xpath=ancestor::*[{up}]")
            # Try inputs first.
            try:
                inputs = container.locator("input")
                m = inputs.count()
            except Exception:
                m = 0
            for j in range(m):
                el = inputs.nth(j)
                try:
                    val = (el.input_value() or "").strip()
                except Exception:
                    continue
                if not val:
                    continue
                if kind == "url" and val.lower().startswith(("http://", "https://")):
                    return val
                if kind == "code" and _looks_like_code(val):
                    return val

            # Then any <code>, <input>, or span with matching text.
            try:
                txt = container.inner_text() or ""
            except Exception:
                txt = ""
            if kind == "url":
                m2 = URL_RE.search(txt)
                if m2:
                    return m2.group(0)
            else:
                for cand in _candidate_codes(txt):
                    return cand
    return ""


def _close_modal(page) -> None:
    dialog = _modal(page)
    for name in ("Close", "Close dialog", "Done", "Dismiss"):
        try:
            btn = dialog.get_by_role("button", name=re.compile(f"^{name}$", re.IGNORECASE)).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=1500)
                return
        except Exception:
            continue
    # Try an aria-label close (X icon).
    try:
        dialog.locator("[aria-label*='close' i]").first.click(timeout=1500)
        return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Code detection helpers
# -----------------------------------------------------------------------------


def _looks_like_code(text: str) -> bool:
    text = text.strip()
    if not text or len(text) < 5 or len(text) > 30:
        return False
    if text.upper() in CODE_BLOCKLIST:
        return False
    if " " in text:
        return False
    if not any(c.isalnum() for c in text):
        return False
    if text.upper() != text and text.lower() != text:
        return False  # mixed case is unlikely for a voucher
    # Require a balance of letters + digits OR be mostly upper-case + digits.
    has_digit = any(c.isdigit() for c in text)
    has_letter = any(c.isalpha() for c in text)
    return has_digit and has_letter or re.fullmatch(r"[A-Z0-9-]{6,}", text.upper())


def _candidate_codes(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for m in CODE_RE.finditer(text.upper()):
        token = m.group(0).strip("-")
        if _looks_like_code(token):
            out.append(token)
    # Prefer tokens with both letters and digits.
    out.sort(
        key=lambda t: (
            0 if any(c.isdigit() for c in t) and any(c.isalpha() for c in t) else 1,
            -len(t),
        )
    )
    return out


# -----------------------------------------------------------------------------
# Persistence + debug
# -----------------------------------------------------------------------------


def _append_csv(rows: list[dict]) -> None:
    new_file = not CODES_CSV.exists()
    with CODES_CSV.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "courseNumber", "code", "url", "students"]
        )
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def _dump_debug(page, course_number: str, iteration: int, note: str = "") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{course_number}-{iteration}-{ts}"
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{stem}.png"), full_page=True)
    except Exception:
        pass
    try:
        html = page.evaluate("document.documentElement.outerHTML")
        (DEBUG_DIR / f"{stem}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass
    if note:
        try:
            (DEBUG_DIR / f"{stem}.txt").write_text(note, encoding="utf-8")
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------


def generate_codes(
    course_number: str,
    base_url: str,
    count: int,
    students: int = 1,
) -> dict:
    if count < 1 or count > 50:
        return {"ok": False, "error": "count must be between 1 and 50"}
    if students < 1 or students > 1000:
        return {"ok": False, "error": "students must be between 1 and 1000"}
    if not STORAGE_STATE.exists():
        return {
            "ok": False,
            "error": "Not signed in. Run the one-time login first (POST /api/login).",
        }

    url = base_url + SG_SUFFIX
    results: list[dict] = []
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            storage_state=str(STORAGE_STATE),
            viewport=VIEWPORT,
        )
        page = context.new_page()

        for i in range(count):
            try:
                try:
                    if i == 0:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    else:
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception as err:
                    raise StepError(
                        "Navigate to course",
                        f"Could not load {url} — {err}",
                    )

                # Step 1: find & click "Request achievement code" anywhere on the page.
                btn, _frame = _find_request_button_anywhere(page)
                _click_found_button(btn)
                _wait_for_modal(page)

                # Step 2: enter student count, click "Request code" in the modal.
                _fill_student_count(page, students)
                _click_submit_in_modal(page)
                _wait_for_success(page)

                # Step 3: copy the code and the URL.
                code, code_url = _extract_code_and_url(page)
                results.append({"code": code, "url": code_url})
                _close_modal(page)
            except StepError as err:
                errors.append(f"Iteration {i + 1} — {err}")
                _dump_debug(page, course_number, i + 1, note=str(err))
                break
            except PlaywrightTimeoutError as err:
                errors.append(
                    f"Iteration {i + 1} — Playwright timeout (no step reported): {err}"
                )
                _dump_debug(page, course_number, i + 1, note=str(err))
                break
            except Exception as err:
                errors.append(f"Iteration {i + 1} — unexpected error: {err}")
                _dump_debug(page, course_number, i + 1, note=str(err))
                break

        browser.close()

    if results:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _append_csv(
            [
                {
                    "timestamp": ts,
                    "courseNumber": course_number,
                    "code": r["code"],
                    "url": r["url"],
                    "students": students,
                }
                for r in results
            ]
        )

    return {
        "ok": len(errors) == 0,
        "requested": count,
        "generated": len(results),
        "students": students,
        "codes": [r["code"] for r in results],
        "results": results,
        "errors": errors,
    }
