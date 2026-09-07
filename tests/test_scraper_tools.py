"""
Unit tests for web scraping and link extraction tools.
"""

from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from tools.scraper_tools import (
    _clean_soup,
    _format_soup_to_markdown,
    extract_links,
    scrape_page_content,
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>JARVIS Test Documentation</title>
    <style>body { color: red; }</style>
    <script>console.log("malicious or useless");</script>
</head>
<body>
    <nav><a href="/home">Home</a></nav>
    <main>
        <h1>Welcome to JARVIS System</h1>
        <p>This is the first paragraph of test content.</p>
        <h2>Capabilities</h2>
        <ul>
            <li>File management</li>
            <li>Web intelligence</li>
        </ul>
        <p>Visit <a href="https://example.com/docs">Documentation</a> or <a href="/relative/path">Relative</a>.</p>
    </main>
    <footer>Copyright 2026 JARVIS Inc.</footer>
</body>
</html>
"""


def test_clean_soup():
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    _clean_soup(soup)

    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find("nav") is None
    assert soup.find("footer") is None
    assert soup.find("h1") is not None


def test_format_soup_to_markdown():
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    _clean_soup(soup)
    md = _format_soup_to_markdown(soup)

    assert "# Welcome to JARVIS System" in md
    assert "This is the first paragraph" in md
    assert "## Capabilities" in md
    assert "- File management" in md
    assert "Copyright" not in md


@patch("tools.scraper_tools.requests.get")
def test_scrape_page_content(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = scrape_page_content("https://test.example.com")
    assert result["title"] == "JARVIS Test Documentation"
    assert "Welcome to JARVIS System" in result["content"]
    assert result["status_code"] == 200


@patch("tools.scraper_tools.requests.get")
def test_extract_links(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    links = extract_links("https://test.example.com")
    assert "https://example.com/docs" in links
    assert "https://test.example.com/relative/path" in links


@patch("tools.scraper_tools.requests.get")
def test_scrape_page_content_truncation(mock_get):
    large_html = f"<html><body><main><p>{'A' * 5000}</p></main></body></html>"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = large_html
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = scrape_page_content("https://large.example.com")
    assert "... [Truncated for token budget]" in result["content"]
    # Check that content length before suffix is bounded
    assert len(result["content"]) <= 3500 + len("\n... [Truncated for token budget]")
