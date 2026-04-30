"""Auto-login to Microsoft Learn using credentials from environment variables.

Reads MS_EMAIL and MS_PASSWORD from a .env file (gitignored) or from the
process environment. Drives the full Microsoft login flow automatically:
  1. Navigate to Microsoft Learn sign-in
  2. Enter email → Next
  3. Enter password → Sign in
  4. Handle "Stay signed in?" → Yes
  5. Wait for authenticated redirect
  6. Save storage state for headless reuse
"""

import os
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from .paths import STORAGE_STATE

load_dotenv()

LOGIN_URL = "https://learn.microsoft.com/en-us/?source=docs"
LEARN_DOMAIN = "learn.microsoft.com"


def _get_credentials() -> tuple[str, str]:
    email = os.environ.get("MS_EMAIL", "").strip()
    password = os.environ.get("MS_PASSWORD", "").strip()
    if not email or not password:
        raise RuntimeError(
            "MS_EMAIL and MS_PASSWORD must be set. "
            "Create a .env file in the webapp/ folder or export them as environment variables."
        )
    return email, password


def _trigger_signin(page) -> None:
    """If we landed on a Learn page that gates the email form behind a
    'Sign in' click, find and click that trigger first."""
    if "login." in page.url.lower():
        return
    triggers = [
        "a[href*='login.microsoftonline.com']",
        "a[href*='login.live.com']",
        "a[href*='/users/sign-in']",
        "button:has-text('Sign in')",
        "a:has-text('Sign in')",
    ]
    for sel in triggers:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(2000)
                return
        except Exception:
            continue


def _fill_email(page, email: str) -> None:
    """Fill the email on the Microsoft login page and click Next."""
    email_input = page.locator("input[type='email'], input[name='loginfmt']").first
    try:
        email_input.wait_for(state="visible", timeout=8000)
    except Exception:
        _trigger_signin(page)
        email_input.wait_for(state="visible", timeout=15000)
    email_input.fill(email)
    email_input.press("Enter")
    page.wait_for_timeout(2000)


def _fill_password(page, password: str) -> None:
    """Fill the password and press Enter to submit."""
    pw_input = page.locator("input[type='password'], input[name='passwd']").first
    pw_input.wait_for(state="visible", timeout=15000)
    pw_input.fill(password)
    pw_input.press("Enter")
    page.wait_for_timeout(2000)


def _handle_stay_signed_in(page) -> None:
    """Click 'Yes' on the 'Stay signed in?' prompt if it appears."""
    try:
        yes_btn = page.locator("#idSIButton9, input[value='Yes']").first
        yes_btn.wait_for(state="visible", timeout=5000)
        yes_btn.click()
    except Exception:
        pass


def _handle_additional_prompts(page) -> None:
    """Dismiss any additional consent/security prompts."""
    # "Don't show this again" checkbox + accept
    try:
        checkbox = page.locator("input[name='DontShowAgain']").first
        if checkbox.count() and checkbox.is_visible():
            checkbox.check()
    except Exception:
        pass

    # Generic accept/continue buttons
    for label in ("Accept", "Continue", "Next", "Yes"):
        try:
            btn = page.get_by_role("button", name=label).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=2000)
        except Exception:
            continue


AUTH_COOKIE_PREFIXES = (
    "ESTSAUTH",   # Azure AD work accounts
    "MSPAuth",    # MS personal accounts (live.com)
    "MSPProf",
    "WLSSC",
    "RPSSecAuth",
    "FedAuth",
)


def _wait_for_authenticated(page, timeout_s: int = 30) -> bool:
    """Wait until we're back on learn.microsoft.com with a signed-in session."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = page.url.lower()
        if LEARN_DOMAIN in url and "login." not in url:
            cookies = page.context.cookies()
            for c in cookies:
                name = c.get("name", "")
                if any(name.startswith(p) for p in AUTH_COOKIE_PREFIXES):
                    return True
        page.wait_for_timeout(500)
    return False


def run_login() -> dict:
    try:
        email, password = _get_credentials()
    except RuntimeError as err:
        return {"ok": False, "error": str(err)}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            _fill_email(page, email)
            _fill_password(page, password)
            _handle_stay_signed_in(page)
            _handle_additional_prompts(page)

            if not _wait_for_authenticated(page, timeout_s=30):
                # May need manual intervention (MFA, captcha, etc.)
                # Wait longer with the window visible for user to complete.
                page.wait_for_timeout(60000)
                if not _wait_for_authenticated(page, timeout_s=10):
                    browser.close()
                    return {
                        "ok": False,
                        "error": (
                            "Auto-login did not complete. Possible causes: "
                            "MFA prompt, captcha, incorrect credentials, or "
                            "the account requires additional verification."
                        ),
                    }

            context.storage_state(path=str(STORAGE_STATE))
            browser.close()
            return {"ok": True, "storage_state": str(STORAGE_STATE)}

        except Exception as err:
            debug_info = ""
            try:
                from .paths import DATA
                debug_dir = DATA / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                shot_path = debug_dir / f"login-{ts}.png"
                html_path = debug_dir / f"login-{ts}.html"
                page.screenshot(path=str(shot_path), full_page=True)
                html_path.write_text(page.content(), encoding="utf-8")
                debug_info = f" (debug: url={page.url}, screenshot={shot_path.name})"
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            return {"ok": False, "error": f"Login failed: {err}{debug_info}"}


if __name__ == "__main__":
    print(run_login())
