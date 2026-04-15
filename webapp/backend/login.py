"""One-time headed login that saves a Playwright storage state.

Detection strategy (any one is enough):
  1. User clicks the injected "Finish" button overlaid on the page.
  2. Microsoft auth cookies (ESTSAUTH*) appear in the context.
  3. The browser window is closed by the user.

We poll every second for up to `timeout_minutes`. As long as the user has
actually signed in by the end, the resulting storage_state.json will contain
the auth cookies and can be reused for headless runs.
"""

import time

from playwright.sync_api import sync_playwright

from .paths import STORAGE_STATE

LOGIN_URL = "https://learn.microsoft.com/users/me/"

FINISH_BANNER_JS = r"""
(() => {
  if (document.getElementById('__mcert_finish')) return;
  const bar = document.createElement('div');
  bar.id = '__mcert_finish';
  bar.style.cssText = [
    'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:2147483647',
    'display:flex', 'align-items:center', 'justify-content:center',
    'gap:12px', 'padding:10px 16px',
    'background:linear-gradient(90deg,#0b1220,#1a2440)',
    'color:#fff', 'font:14px/1.4 "Segoe UI",system-ui,sans-serif',
    'box-shadow:0 2px 10px rgba(0,0,0,.4)'
  ].join(';');
  bar.innerHTML = `
    <span>After you finish signing in here, click <b>Finish &amp; save session</b>.</span>
    <button id="__mcert_finish_btn"
      style="background:#3b8cff;color:#fff;border:0;border-radius:8px;
             padding:8px 14px;font:inherit;cursor:pointer">
      Finish &amp; save session
    </button>`;
  document.documentElement.appendChild(bar);
  document.getElementById('__mcert_finish_btn').addEventListener('click', () => {
    window.__mcert_finished = true;
  });
})();
"""


def _has_auth_cookies(context) -> bool:
    """True when Microsoft identity cookies are present in the context."""
    try:
        cookies = context.cookies()
    except Exception:
        return False
    for c in cookies:
        name = c.get("name", "")
        if name.startswith("ESTSAUTH") or name == "ESTSAUTHPERSISTENT":
            return True
    return False


def _finish_clicked(page) -> bool:
    try:
        return bool(page.evaluate("window.__mcert_finished === true"))
    except Exception:
        return False


def _inject_banner(page) -> None:
    try:
        page.evaluate(FINISH_BANNER_JS)
    except Exception:
        pass


def run_login(timeout_minutes: int = 10) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Re-inject the banner on every navigation so it survives redirects through
        # login.microsoftonline.com and back to learn.microsoft.com.
        page.on("load", lambda _: _inject_banner(page))
        page.goto(LOGIN_URL)

        deadline = time.time() + timeout_minutes * 60
        closed = False
        success = False

        def on_close(_):
            nonlocal closed
            closed = True

        page.on("close", on_close)

        while time.time() < deadline:
            if closed:
                break
            if _finish_clicked(page):
                success = True
                break
            if _has_auth_cookies(context):
                # Give the page a moment to finish any post-login redirects.
                page.wait_for_timeout(1500)
                success = True
                break
            try:
                page.wait_for_timeout(1000)
            except Exception:
                break

        # If the user closed the window manually but we still have auth cookies,
        # count that as success.
        if not success and _has_auth_cookies(context):
            success = True

        if success:
            try:
                context.storage_state(path=str(STORAGE_STATE))
            except Exception as err:
                browser.close()
                return {"ok": False, "error": f"Could not save storage state: {err}"}

        try:
            browser.close()
        except Exception:
            pass

    if not success:
        return {
            "ok": False,
            "error": (
                "Did not detect a signed-in session. Make sure you signed in with your "
                "Microsoft account in the opened browser window, then click "
                "'Finish & save session'."
            ),
        }
    return {"ok": True, "storage_state": str(STORAGE_STATE)}


if __name__ == "__main__":
    print(run_login())
