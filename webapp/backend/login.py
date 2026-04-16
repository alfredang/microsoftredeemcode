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

LOGIN_URL = "https://learn.microsoft.com/en-us/users/sign-in"
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


def _fill_email(page, email: str) -> None:
    """Fill the email on the Microsoft login page and click Next."""
    email_input = page.locator("input[type='email'], input[name='loginfmt']").first
    email_input.wait_for(state="visible", timeout=15000)
    email_input.fill(email)

    next_btn = page.locator("input[type='submit'], #idSIButton9").first
    next_btn.click()
    page.wait_for_timeout(2000)


def _fill_password(page, password: str) -> None:
    """Fill the password and click Sign in."""
    pw_input = page.locator("input[type='password'], input[name='passwd']").first
    pw_input.wait_for(state="visible", timeout=15000)
    pw_input.fill(password)

    sign_in_btn = page.locator("input[type='submit'], #idSIButton9").first
    sign_in_btn.click()
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


def _wait_for_authenticated(page, timeout_s: int = 30) -> bool:
    """Wait until we're back on learn.microsoft.com with a signed-in session."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = page.url.lower()
        if LEARN_DOMAIN in url:
            # Check for auth cookies
            cookies = page.context.cookies()
            for c in cookies:
                if c.get("name", "").startswith("ESTSAUTH"):
                    return True
            # Also check if we can see profile-related elements
            try:
                body = page.inner_text("body").lower()
                if "sign out" in body or "my profile" in body or "my learning" in body:
                    return True
            except Exception:
                pass
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
            try:
                browser.close()
            except Exception:
                pass
            return {"ok": False, "error": f"Login failed: {err}"}


if __name__ == "__main__":
    print(run_login())
