from playwright.sync_api import sync_playwright


class BrowserManager:
    """Manage a shared Playwright browser instance."""

    def __init__(self, headless=True):
        self._headless = headless
        self._playwright = None
        self._browser = None

    @property
    def browser(self):
        if self._browser is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self._headless)
        return self._browser

    def new_page(self):
        """Create an isolated page and return both page and context."""
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1024},
        )
        page = context.new_page()
        return page, context

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
