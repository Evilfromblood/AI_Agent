"""
Unit tests for browser automation tools and BrowserController.
"""

from unittest.mock import MagicMock, patch
from tools.browser_tools import BrowserController, browser_controller


def test_browser_controller_singleton():
    b1 = BrowserController()
    b2 = BrowserController()
    assert b1 is b2
    assert b1 is browser_controller


def test_browser_controller_methods_mocked():
    ctrl = BrowserController()
    mock_driver = MagicMock()
    mock_driver.title = "Mocked Page Title"
    mock_driver.current_url = "https://mock.example.com"
    mock_driver.page_source = "<html><head><title>Mocked</title></head><body><main><h1>Mock Content</h1></main></body></html>"

    ctrl.driver = mock_driver

    try:
        # Test open_url
        res = ctrl.open_url("mock.example.com")
        assert "Successfully navigated" in res
        mock_driver.get.assert_called_with("https://mock.example.com")

        # Test get_page_source_soup
        soup = ctrl.get_page_source_soup()
        assert soup.find("h1").text == "Mock Content"

        # Test get_clean_page_content
        content_dict = ctrl.get_clean_page_content()
        assert content_dict["title"] == "Mocked Page Title"
        assert "# Mock Content" in content_dict["content"]

        # Test close_browser
        close_res = ctrl.close_browser()
        assert "closed successfully" in close_res
        assert ctrl.driver is None
    finally:
        ctrl.driver = None
