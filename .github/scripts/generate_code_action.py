"""GitHub Actions script: log in to Microsoft Learn and generate an achievement code.

Reads inputs from environment variables (set by the workflow):
  COURSE_NUMBER, COURSE_URL, STUDENTS, REQUEST_ID, MS_EMAIL, MS_PASSWORD

Writes the result to /tmp/result.json for the workflow to pick up.
"""

import json
import os
import re
import time

from playwright.sync_api import sync_playwright

SG_SUFFIX = "?WT.mc_id=ilt_partner_webpage_wwl&ocid=5238477"

COURSE_NUMBER = os.environ["COURSE_NUMBER"]
COURSE_URL = os.environ["COURSE_URL"] + SG_SUFFIX
STUDENTS = int(os.environ.get("STUDENTS", "1"))
REQUEST_ID = os.environ["REQUEST_ID"]
MS_EMAIL = os.environ["MS_EMAIL"]
MS_PASSWORD = os.environ["MS_PASSWORD"]

RESULT_PATH = "/tmp/result.json"


def write_result(ok, code="", url="", error=""):
    with open(RESULT_PATH, "w") as f:
        json.dump(
            {
                "ok": ok,
                "requestId": REQUEST_ID,
                "courseNumber": COURSE_NUMBER,
                "students": STUDENTS,
                "code": code,
                "url": url,
                "error": error,
            },
            f,
        )


# ---------------------------------------------------------------------------
# Microsoft Login
# ---------------------------------------------------------------------------

def dismiss_cookie_banners(page):
    """Dismiss any cookie consent or privacy banners that block the page."""
    for selector in [
        "#wcpConsentBannerCtrl button",
        "button[id*='cookie' i]",
        "button[id*='consent' i]",
        "button[id*='accept' i]",
        "[aria-label*='Accept' i]",
        "[aria-label*='cookie' i]",
        "button:has-text('Accept')",
        "button:has-text('Accept all')",
        "button:has-text('I agree')",
        "button:has-text('OK')",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=2000)
                print(f"  Dismissed banner: {selector}")
                page.wait_for_timeout(500)
        except Exception:
            continue


def login(page):
    print(f"  MS_EMAIL length: {len(MS_EMAIL)}")
    print(f"  MS_PASSWORD length: {len(MS_PASSWORD)}")

    if not MS_EMAIL or not MS_PASSWORD:
        raise RuntimeError("MS_EMAIL or MS_PASSWORD is empty — check GitHub Secrets.")

    print("Navigating to Microsoft login page...")
    page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    dismiss_cookie_banners(page)
    page.screenshot(path="/tmp/debug-login-1.png")
    print(f"  URL after load: {page.url}")

    # --- Email ---
    print("Typing email...")
    email_input = page.locator("input[type='email'], input[name='loginfmt']").first
    email_input.wait_for(state="visible", timeout=30000)
    email_input.click()
    page.wait_for_timeout(300)
    email_input.press_sequentially(MS_EMAIL, delay=50)
    page.wait_for_timeout(500)

    # Verify the value landed
    typed_val = email_input.input_value()
    print(f"  Email field value length: {len(typed_val)}")
    page.screenshot(path="/tmp/debug-login-2.png")

    page.wait_for_timeout(1000)
    next_btn = page.locator("#idSIButton9, input[type='submit'], button[type='submit']").first
    next_btn.wait_for(state="visible", timeout=15000)
    next_btn.click()
    page.wait_for_timeout(5000)
    page.screenshot(path="/tmp/debug-login-3.png")
    print(f"  URL after email: {page.url}")

    # --- Password ---
    print("Typing password...")
    pw_input = page.locator("input[type='password'], input[name='passwd']").first
    pw_input.wait_for(state="visible", timeout=30000)
    pw_input.click()
    page.wait_for_timeout(300)
    pw_input.press_sequentially(MS_PASSWORD, delay=50)
    page.wait_for_timeout(1000)
    page.screenshot(path="/tmp/debug-login-4.png")

    sign_in_btn = page.locator("#idSIButton9, input[type='submit'], button[type='submit']").first
    sign_in_btn.wait_for(state="visible", timeout=15000)
    sign_in_btn.click()
    page.wait_for_timeout(5000)
    page.screenshot(path="/tmp/debug-login-5.png")
    print(f"  URL after password: {page.url}")

    # --- Stay signed in? ---
    try:
        yes_btn = page.locator("#idSIButton9, input[value='Yes']").first
        yes_btn.wait_for(state="visible", timeout=8000)
        yes_btn.click()
        page.wait_for_timeout(5000)
    except Exception:
        pass

    page.screenshot(path="/tmp/debug-login-6.png")
    print(f"  Final URL: {page.url}")

    # Verify login worked
    url = page.url.lower()
    if "login.live.com" in url or "login.microsoftonline.com" in url:
        raise RuntimeError(
            f"Login appears to have failed — still on login page: {page.url}. "
            "Check debug screenshots and verify GitHub Secrets MS_EMAIL / MS_PASSWORD are correct."
        )

    print("Login complete.")


# ---------------------------------------------------------------------------
# Achievement Code Generation
# ---------------------------------------------------------------------------

def find_request_button(page, timeout_s=30):
    """Scroll through the page and find the Request achievement code button."""
    # Scroll to load lazy content
    try:
        page.evaluate("""
            async () => {
                const h = document.body.scrollHeight;
                for (let y = 0; y <= h; y += 300) {
                    window.scrollTo(0, y);
                    await new Promise(r => setTimeout(r, 100));
                }
                window.scrollTo(0, 0);
            }
        """)
    except Exception:
        pass

    patterns = [
        re.compile(r"Request achievement code", re.IGNORECASE),
        re.compile(r"Request a code", re.IGNORECASE),
        re.compile(r"Get achievement code", re.IGNORECASE),
    ]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for pat in patterns:
            try:
                btn = page.get_by_role("button", name=pat).first
                if btn.count() and btn.is_visible():
                    return btn
            except Exception:
                pass
            try:
                loc = page.locator("button, a, [role=button]").filter(has_text=pat).first
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                pass
        page.wait_for_timeout(500)
    return None


def generate(page):
    print(f"Navigating to course page: {COURSE_URL}")
    page.goto(COURSE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    # Step 1: Find and click Request achievement code
    print("Step 1: Finding 'Request achievement code' button...")
    btn = find_request_button(page)
    if not btn:
        page.screenshot(path="/tmp/debug-step1.png", full_page=True)
        raise RuntimeError(
            "Could not find 'Request achievement code' button. "
            "Check /tmp/debug-step1.png"
        )
    btn.scroll_into_view_if_needed()
    btn.click()
    print("Clicked. Waiting for modal...")

    # Wait for modal
    dialog = page.locator("[role='dialog'], [aria-modal='true'], dialog").first
    dialog.wait_for(state="visible", timeout=10000)
    print("Modal opened.")

    # Step 2: Fill student count and click Request code
    print(f"Step 2: Filling student count = {STUDENTS}...")
    for sel in ["input[type='number']", "input[inputmode='numeric']", "input"]:
        try:
            inp = dialog.locator(sel).first
            if inp.count() and inp.is_visible() and inp.is_editable():
                inp.fill(str(STUDENTS))
                break
        except Exception:
            continue

    submit_re = re.compile(r"^\s*Request code\s*$", re.IGNORECASE)
    submit_btn = dialog.get_by_role("button", name=submit_re).first
    submit_btn.wait_for(state="visible", timeout=10000)
    for _ in range(15):
        try:
            if submit_btn.is_enabled():
                break
        except Exception:
            pass
        page.wait_for_timeout(200)
    submit_btn.click()
    print("Clicked 'Request code'. Waiting for result...")

    # Wait for success
    deadline = time.time() + 30
    ready_re = re.compile(r"code is ready", re.IGNORECASE)
    while time.time() < deadline:
        try:
            text = dialog.inner_text()
            if ready_re.search(text):
                break
        except Exception:
            pass
        page.wait_for_timeout(500)
    else:
        page.screenshot(path="/tmp/debug-step2.png", full_page=True)
        raise RuntimeError("Timed out waiting for 'code is ready' message.")

    print("Code is ready! Extracting...")

    # Step 3: Extract code and URL
    code = ""
    url = ""

    # Read inputs in the dialog
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
        if not url and val.startswith("http"):
            url = val
        elif not code and len(val) >= 5 and not val.startswith("http"):
            code = val

    # Fallback: look near Copy buttons
    if not code:
        try:
            copy_btn = dialog.get_by_role("button", name=re.compile(r"copy\s*code", re.IGNORECASE)).first
            if copy_btn.count():
                for up in range(1, 4):
                    container = copy_btn.locator(f"xpath=ancestor::*[{up}]")
                    try:
                        inp = container.locator("input").first
                        val = inp.input_value().strip()
                        if val and len(val) >= 5:
                            code = val
                            break
                    except Exception:
                        continue
        except Exception:
            pass

    if not url:
        try:
            copy_url_btn = dialog.get_by_role("button", name=re.compile(r"copy\s*url", re.IGNORECASE)).first
            if copy_url_btn.count():
                for up in range(1, 4):
                    container = copy_url_btn.locator(f"xpath=ancestor::*[{up}]")
                    try:
                        inp = container.locator("input").first
                        val = inp.input_value().strip()
                        if val and val.startswith("http"):
                            url = val
                            break
                    except Exception:
                        continue
        except Exception:
            pass

    if not code:
        page.screenshot(path="/tmp/debug-step3.png", full_page=True)
        raise RuntimeError("Could not extract the achievement code from the modal.")

    print(f"Success! Code: {code}, URL: {url}")
    return code, url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Request {REQUEST_ID}: course={COURSE_NUMBER}, students={STUDENTS}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 860})
        page = context.new_page()

        try:
            login(page)
            code, url = generate(page)
            write_result(True, code=code, url=url)
        except Exception as err:
            print(f"Error: {err}")
            try:
                page.screenshot(path="/tmp/debug-error.png", full_page=True)
            except Exception:
                pass
            write_result(False, error=str(err))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
