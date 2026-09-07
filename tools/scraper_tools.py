"""
Web scraping and parsing toolset for JARVIS.
Extracts clean page titles, readable markdown text, and links using requests and BeautifulSoup.
"""

from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
from tools.registry import registry

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _clean_soup(soup: BeautifulSoup) -> None:
    """Remove scripts, styles, navigation, footer, header, and hidden elements."""
    tags_to_remove = ["script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"]
    for tag in soup.find_all(tags_to_remove):
        tag.decompose()


def _format_soup_to_markdown(soup: BeautifulSoup) -> str:
    """Convert main HTML body elements into clean structured text/markdown."""
    lines: List[str] = []

    # Target main content container if available
    body = soup.find("main") or soup.find("article") or soup.find("body") or soup

    for element in body.descendants:
        if element.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(element.name[1])
            text = element.get_text(strip=True)
            if text:
                lines.append(f"\n{'#' * level} {text}\n")
        elif element.name == "p":
            text = element.get_text(strip=True)
            if text:
                lines.append(f"{text}\n")
        elif element.name == "li":
            text = element.get_text(strip=True)
            if text:
                lines.append(f"- {text}")

    content = "\n".join(lines).strip()
    if not content:
        # Fallback to plain text if headings/paragraphs weren't isolated
        content = soup.get_text(separator="\n", strip=True)

    # Collapse excessive newlines
    import re
    cleaned = re.sub(r"\n{3,}", "\n\n", content)
    return cleaned[:8000]  # Cap length to prevent context explosion


@registry.register
def scrape_page_content(url: str) -> Dict[str, Any]:
    """
    Fetch raw HTML from a URL, strip boilerplate/unnecessary tags, and return clean markdown text and title.
    :param url: Target web URL (http or https)
    :return: Dictionary containing 'title', 'url', and 'content' markdown text
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title
        title = soup.title.string.strip() if soup.title and soup.title.string else "No title found"

        # Clean unnecessary elements
        _clean_soup(soup)

        # Convert to clean markdown text
        markdown_text = _format_soup_to_markdown(soup)

        return {
            "title": title,
            "url": url,
            "status_code": response.status_code,
            "content": markdown_text,
        }
    except requests.RequestException as re_err:
        return {
            "error": f"Failed to fetch URL '{url}': {str(re_err)}",
            "url": url,
        }
    except Exception as e:
        return {
            "error": f"Error parsing page '{url}': {type(e).__name__} - {str(e)}",
            "url": url,
        }


@registry.register
def extract_links(url: str) -> List[str]:
    """
    Extract all valid hyperlinks from a webpage, resolved as absolute URLs.
    :param url: Target web URL to extract links from
    :return: List of unique absolute HTTP/HTTPS links
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        _clean_soup(soup)

        links: set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            # Ignore empty, anchor-only, or javascript links
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            full_url = urljoin(url, href)
            parsed = urlparse(full_url)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                links.add(full_url)

        return sorted(list(links))[:100]  # Cap at 100 links
    except requests.RequestException as re_err:
        return [f"Error extracting links from '{url}': {str(re_err)}"]
    except Exception as e:
        return [f"Error parsing links from '{url}': {type(e).__name__} - {str(e)}"]
