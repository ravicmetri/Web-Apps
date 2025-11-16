import os
import pytest
import requests

# Read base URL from environment
BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture
def test_user():
    """
    Test user precondition — ensure this user exists in your test environment:
    username=alice, password=Password123!, display_name=Alice
    """
    return {"username": "alice", "password": "Password123!", "display_name": "Alice"}


def _fill_credentials(page, username, password):
    username_selectors = 'input[name="username"], input#username, input[name="email"], input[type="email"]'
    password_selectors = 'input[name="password"], input#password'
    page.wait_for_selector(username_selectors, timeout=5000)
    page.wait_for_selector(password_selectors, timeout=5000)
    page.fill(username_selectors, username)
    page.fill(password_selectors, password)


def _click_sign_in(page):
    selectors = [
        'button[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Sign In")',
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'input[type="submit"]',
    ]
    for sel in selectors:
        try:
            locator = page.locator(sel)
            if locator.count() > 0:
                locator.first.click()
                return
        except Exception:
            pass
    # fallback: press Enter in password field
    page.keyboard.press("Enter")


@pytest.fixture
def login_via_ui(page, base_url, test_user):
    """
    Fixture that performs a UI login and returns the page at /dashboard.
    Reusable across tests that require a logged-in session.
    """
    login_url = f"{base_url}/login"
    page.goto(login_url)
    page.wait_for_load_state("networkidle")
    _fill_credentials(page, test_user["username"], test_user["password"])
    _click_sign_in(page)
    # Wait for navigation to dashboard (works for client-side or server redirects)
    page.wait_for_url("**/dashboard", timeout=5000)
    return page


# Capture screenshots on failure
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        page = item.funcargs.get("page") or item.funcargs.get("login_via_ui")
        if page:
            screenshots_dir = os.path.join(os.getcwd(), "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            # sanitize test name for filesystem
            safe_name = "".join(c if c.isalnum() or c in "-._" else "_" for c in item.name)
            screenshot_path = os.path.join(screenshots_dir, f"{safe_name}.png")
            try:
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"[pytest-playwright] Screenshot saved to {screenshot_path}")
            except Exception as e:
                print(f"[pytest-playwright] Failed to capture screenshot: {e}")


def _get_requests_session_from_browser(page):
    """
    Build a requests.Session with cookies copied from the Playwright browser context
    so we can perform authenticated API/HTTP checks using requests.
    """
    session = requests.Session()
    try:
        cookies = page.context.cookies()
        for c in cookies:
            session.cookies.set(c.get("name"), c.get("value"), domain=c.get("domain"), path=c.get("path", "/"))
    except Exception:
        pass
    return session


def test_valid_login_redirects_to_dashboard(login_via_ui, test_user, base_url):
    """
    TC-LOGIN-001
    Preconditions: test user alice exists (username=alice; password=Password123!)
    Steps:
      1. Open {BASE_URL}/login
      2. enter username and password
      3. click sign in
    Expected:
      redirect to /dashboard and page contains 'Welcome, Alice'
    """
    page = login_via_ui

    # UI expectations
    assert "/dashboard" in page.url, f"Expected to be on /dashboard, but was on {page.url}"
    welcome_locator = page.locator(f"text=Welcome, {test_user['display_name']}")
    assert welcome_locator.count() > 0 and welcome_locator.is_visible(), "Welcome message not found on dashboard"

    # API-backed verification using requests with browser cookies
    session = _get_requests_session_from_browser(page)
    try:
        resp = session.get(f"{base_url}/dashboard", timeout=5)
        assert resp.status_code == 200, f"GET /dashboard returned {resp.status_code}"
        assert f"Welcome, {test_user['display_name']}" in resp.text, "Welcome message missing from dashboard HTML response"
    except requests.RequestException as e:
        pytest.fail(f"API check failed: {e}")
