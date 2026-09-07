"""
Browser automation toolset using Selenium and BeautifulSoup.
Provides singleton BrowserController for automated web navigation and interaction.
"""

from typing import Any, Dict, Optional
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from config import config
from tools.registry import registry
from tools.scraper_tools import _clean_soup, _format_soup_to_markdown

BY_MAP = {
    "css": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "id": By.ID,
    "name": By.NAME,
    "tag": By.TAG_NAME,
    "class": By.CLASS_NAME,
    "link_text": By.LINK_TEXT,
}


class BrowserController:
    """
    Singleton controller managing an automated Chrome browser instance.
    """
    _instance: Optional["BrowserController"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(BrowserController, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, headless: Optional[bool] = None):
        if getattr(self, "_initialized", False):
            return

        self.headless = headless if headless is not None else config.headless_browser
        self.driver: Optional[webdriver.Chrome] = None
        self._initialized = True

    def _ensure_driver(self) -> webdriver.Chrome:
        """Initialize Chrome WebDriver if not already running."""
        if self.driver is not None:
            try:
                # Ping driver to ensure window is still open
                _ = self.driver.current_window_handle
                return self.driver
            except Exception:
                self.close_browser()

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(f"user-agent={DEFAULT_HEADERS['User-Agent']}")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        try:
            # First try webdriver-manager
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception:
            # Fallback to standard selenium driver resolution
            self.driver = webdriver.Chrome(options=chrome_options)

        self.driver.set_page_load_timeout(config.browser_page_load_timeout)
        self.driver.implicitly_wait(5)
        return self.driver

    def open_url(self, url: str) -> str:
        """
        Navigate browser to the specified URL.
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        driver = self._ensure_driver()
        try:
            driver.get(url)
            title = driver.title or "No title"
            return f"Successfully navigated to '{url}'. Page Title: '{title}'"
        except Exception as e:
            return f"Error opening URL '{url}': {str(e)}"

    def wait_for_page_load(self, timeout: int = 5) -> str:
        """Wait for page readyState to be complete and dynamic DOM to settle."""
        driver = self._ensure_driver()
        import time
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            time.sleep(0.5)  # Brief settling pause for SPA re-rendering
            return f"Page loaded successfully. Current URL: {driver.current_url}"
        except Exception as e:
            return f"Wait for page load finished: {str(e)}"

    def click_element(self, by: str, selector: str) -> str:
        """
        Click on an element matching selector. Supports 'css', 'xpath', 'id', 'name', 'class', 'tag'.
        Falls back to JavaScript click if standard click is intercepted.
        """
        by_key = by.strip().lower()
        if by_key not in BY_MAP:
            return f"Error: Unsupported locator type '{by}'. Supported: {list(BY_MAP.keys())}"

        driver = self._ensure_driver()
        by_type = BY_MAP[by_key]

        try:
            wait = WebDriverWait(driver, 10)
            elem = wait.until(EC.element_to_be_clickable((by_type, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            try:
                elem.click()
            except Exception:
                # JavaScript click fallback for intercepted elements or overlays
                driver.execute_script("arguments[0].click();", elem)

            return f"Successfully clicked element '{selector}' (using {by}). Current URL: {driver.current_url}"
        except Exception as e:
            # Final attempt via JS query selector if element wasn't clickable directly
            try:
                driver.execute_script(f"document.querySelector('{selector}').click();")
                return f"Successfully clicked element '{selector}' via JS fallback. Current URL: {driver.current_url}"
            except Exception:
                return f"Error clicking element '{selector}' (by={by}): {str(e)}"

    def type_text(self, by: str, selector: str, text: str, press_enter: bool = False) -> str:
        """
        Type text into an input field matching selector. Supports pressing Enter afterwards.
        """
        by_key = by.strip().lower()
        if by_key not in BY_MAP:
            return f"Error: Unsupported locator type '{by}'. Supported: {list(BY_MAP.keys())}"

        driver = self._ensure_driver()
        by_type = BY_MAP[by_key]

        try:
            wait = WebDriverWait(driver, 10)
            elem = wait.until(EC.visibility_of_element_located((by_type, selector)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
            elem.clear()
            elem.send_keys(text)
            if press_enter:
                elem.send_keys(Keys.RETURN)
            return f"Successfully typed text into '{selector}' (press_enter={press_enter})."
        except Exception as e:
            return f"Error typing into '{selector}' (by={by}): {str(e)}"

    def get_page_source_soup(self) -> BeautifulSoup:
        """
        Pass the live rendered DOM from Selenium into BeautifulSoup.
        """
        driver = self._ensure_driver()
        html = driver.page_source
        return BeautifulSoup(html, "html.parser")

    def get_clean_page_content(self) -> Dict[str, Any]:
        """
        Extract title and clean markdown from current live browser page.
        """
        if not self.driver:
            return {"error": "Browser is not currently open."}

        soup = self.get_page_source_soup()
        title = self.driver.title or "No title"
        url = self.driver.current_url
        _clean_soup(soup)
        markdown = _format_soup_to_markdown(soup)
        return {
            "title": title,
            "url": url,
            "content": markdown,
        }

    def close_browser(self) -> str:
        """
        Close the automated browser instance.
        """
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            finally:
                self.driver = None
            return "Browser closed successfully."
        return "Browser was not open."


# Global controller instance
browser_controller = BrowserController()


# Register wrapper functions into the ToolRegistry
@registry.register
def open_url(url: str) -> str:
    """
    Open a webpage in the automated browser.
    :param url: Web URL to navigate to
    :return: Navigation status and page title
    """
    return browser_controller.open_url(url)


@registry.register
def click_element(by: str, selector: str) -> str:
    """
    Click an element on the current webpage using a selector.
    :param by: Locator strategy ('css', 'xpath', 'id', 'name', 'tag')
    :param selector: The selector string (e.g. '#submit-btn', '//button[text()="Search"]')
    :return: Action result message
    """
    return browser_controller.click_element(by=by, selector=selector)


@registry.register
def type_text(by: str, selector: str, text: str, press_enter: bool = False) -> str:
    """
    Type text into an input field on the current webpage.
    :param by: Locator strategy ('css', 'xpath', 'id', 'name')
    :param selector: The selector string for the input element
    :param text: Text to type into the field
    :param press_enter: Whether to simulate pressing Enter key after typing (default: False)
    :return: Action result message
    """
    return browser_controller.type_text(by=by, selector=selector, text=text, press_enter=press_enter)


@registry.register
def get_browser_page_content() -> Dict[str, Any]:
    """
    Extract readable text/content from the currently opened browser tab.
    :return: Dictionary containing title, url, and content
    """
    return browser_controller.get_clean_page_content()


@registry.register
def wait_for_page_load(timeout: int = 5) -> str:
    """
    Wait for the currently opened browser tab to finish loading dynamic scripts and DOM.
    :param timeout: Maximum seconds to wait (default: 5)
    :return: Status message
    """
    return browser_controller.wait_for_page_load(timeout=timeout)


@registry.register
def close_browser() -> str:
    """
    Close the automated browser window and release resources.
    :return: Status message
    """
    return browser_controller.close_browser()
