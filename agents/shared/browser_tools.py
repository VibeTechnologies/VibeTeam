from __future__ import annotations

"""
Shared Browser Automation tool functions for all agent frameworks.

These functions provide web browsing and research capabilities using
playwright for real browser automation. Falls back to simple HTTP
requests when playwright is not available.

Usage:
    # AutoGen - use directly as FunctionTool
    from agents.shared.browser_tools import web_search, fetch_webpage, take_screenshot

    # CrewAI - wrap in BaseTool
    from agents.shared.browser_tools import fetch_webpage_sync
    class BrowserTool(BaseTool):
        def _run(self, url): return fetch_webpage_sync(url)

    # OpenHands - use for context injection
    from agents.shared.browser_tools import get_webpage_context
"""

import asyncio
import os
from typing import Any
from urllib.parse import quote_plus

# Check for playwright availability
try:
    from playwright.async_api import Browser, Page, async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    Browser = None
    Page = None


# Global browser instance for reuse
_browser_instance: "Browser | None" = None
_playwright_instance = None


async def _get_browser() -> "Browser":
    """Get or create a browser instance."""
    global _browser_instance, _playwright_instance

    if not PLAYWRIGHT_AVAILABLE:
        raise ImportError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    if _browser_instance is None:
        _playwright_instance = await async_playwright().start()
        _browser_instance = await _playwright_instance.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )

    return _browser_instance


async def _cleanup_browser():
    """Clean up browser resources."""
    global _browser_instance, _playwright_instance

    if _browser_instance:
        await _browser_instance.close()
        _browser_instance = None

    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None


async def fetch_webpage(url: str, timeout_ms: int = 30000) -> str:
    """Fetch and parse a webpage, extracting readable text content.

    Args:
        url: The URL to fetch
        timeout_ms: Timeout in milliseconds (default: 30000)

    Returns:
        Extracted text content from the webpage
    """
    if PLAYWRIGHT_AVAILABLE:
        return await _fetch_with_playwright(url, timeout_ms)
    else:
        return await _fetch_with_urllib(url)


async def _fetch_with_playwright(url: str, timeout_ms: int = 30000) -> str:
    """Fetch webpage using playwright for full JS rendering."""
    try:
        browser = await _get_browser()
        page = await browser.new_page()

        try:
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            # Wait a bit for dynamic content
            await page.wait_for_timeout(1000)

            # Extract text content, removing scripts and styles
            content = await page.evaluate("""
                () => {
                    // Remove script and style elements
                    const elements = document.querySelectorAll('script, style, nav, footer, header, aside');
                    elements.forEach(el => el.remove());

                    // Get text content
                    const body = document.body;
                    if (!body) return 'No content found';

                    // Extract text while preserving some structure
                    const getText = (node) => {
                        if (node.nodeType === Node.TEXT_NODE) {
                            return node.textContent.trim();
                        }
                        if (node.nodeType !== Node.ELEMENT_NODE) return '';

                        const tag = node.tagName.toLowerCase();
                        if (['script', 'style', 'nav', 'footer'].includes(tag)) return '';

                        const children = Array.from(node.childNodes).map(getText).filter(t => t).join(' ');

                        if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {
                            return '\\n## ' + children + '\\n';
                        }
                        if (tag === 'p') return children + '\\n';
                        if (tag === 'li') return '- ' + children + '\\n';
                        if (tag === 'br') return '\\n';

                        return children;
                    };

                    return getText(body);
                }
            """)

            # Clean up and truncate
            content = " ".join(content.split())  # Normalize whitespace
            if len(content) > 8000:
                content = content[:8000] + "... (truncated)"

            return f"=== Content from {url} ===\n\n{content}"

        finally:
            await page.close()

    except Exception as e:
        return f"Error fetching {url}: {e}"


async def _fetch_with_urllib(url: str) -> str:
    """Fallback fetch using urllib (no JS rendering)."""
    import urllib.error
    import urllib.request
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []
            self.skip = False

        def handle_starttag(self, tag, attrs):
            if tag in ["script", "style", "nav", "footer", "header"]:
                self.skip = True

        def handle_endtag(self, tag):
            if tag in ["script", "style", "nav", "footer", "header"]:
                self.skip = False

        def handle_data(self, data):
            if not self.skip:
                text = data.strip()
                if text:
                    self.text.append(text)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VibeTeam Browser Bot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8", errors="ignore")

        parser = TextExtractor()
        parser.feed(html)
        text = " ".join(parser.text)

        if len(text) > 8000:
            text = text[:8000] + "... (truncated)"

        return f"=== Content from {url} (no JS) ===\n\n{text}"

    except urllib.error.URLError as e:
        return f"Error fetching URL: {e.reason}"
    except Exception as e:
        return f"Error fetching webpage: {e}"


def fetch_webpage_sync(url: str, timeout_ms: int = 30000) -> str:
    """Synchronous version of fetch_webpage for CrewAI tools."""
    return asyncio.run(fetch_webpage(url, timeout_ms))


async def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo (no API key required).

    Args:
        query: Search query
        num_results: Number of results to return (default: 5)

    Returns:
        Search results with titles, URLs, and snippets
    """
    # Try DuckDuckGo HTML search (no API key needed)
    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

        if PLAYWRIGHT_AVAILABLE:
            browser = await _get_browser()
            page = await browser.new_page()

            try:
                await page.goto(search_url, timeout=15000, wait_until="domcontentloaded")

                # Extract search results
                results = await page.evaluate("""
                    () => {
                        const results = [];
                        const items = document.querySelectorAll('.result');

                        for (let i = 0; i < Math.min(items.length, 10); i++) {
                            const item = items[i];
                            const titleEl = item.querySelector('.result__title');
                            const snippetEl = item.querySelector('.result__snippet');
                            const linkEl = item.querySelector('.result__url');

                            if (titleEl) {
                                results.push({
                                    title: titleEl.textContent.trim(),
                                    snippet: snippetEl ? snippetEl.textContent.trim() : '',
                                    url: linkEl ? linkEl.textContent.trim() : ''
                                });
                            }
                        }
                        return results;
                    }
                """)

                if not results:
                    return f"No search results found for: {query}"

                output = f"=== Web Search Results for: {query} ===\n\n"
                for i, r in enumerate(results[:num_results], 1):
                    output += f"{i}. **{r['title']}**\n"
                    output += f"   URL: {r['url']}\n"
                    output += f"   {r['snippet']}\n\n"

                return output

            finally:
                await page.close()

        else:
            # Fallback without playwright
            return f"""=== Web Search Results for: {query} ===

Note: Playwright not available for full search results.
Install with: pip install playwright && playwright install chromium

For now, please use your knowledge to provide information about: {query}
"""

    except Exception as e:
        return f"Error searching: {e}"


def web_search_sync(query: str, num_results: int = 5) -> str:
    """Synchronous version of web_search for CrewAI tools."""
    return asyncio.run(web_search(query, num_results))


async def take_screenshot(url: str, full_page: bool = False) -> dict[str, Any]:
    """Take a screenshot of a webpage.

    Args:
        url: URL to screenshot
        full_page: Whether to capture full page or just viewport

    Returns:
        Dict with screenshot path and metadata
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "success": False,
            "error": "Playwright not installed",
            "path": None,
        }

    try:
        browser = await _get_browser()
        page = await browser.new_page()

        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)  # Wait for rendering

            # Create screenshots directory
            screenshots_dir = os.path.join(os.getcwd(), ".screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            # Generate filename from URL
            import hashlib
            from datetime import datetime

            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{url_hash}_{timestamp}.png"
            filepath = os.path.join(screenshots_dir, filename)

            await page.screenshot(path=filepath, full_page=full_page)

            return {
                "success": True,
                "path": filepath,
                "url": url,
                "full_page": full_page,
                "title": await page.title(),
            }

        finally:
            await page.close()

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "path": None,
        }


def take_screenshot_sync(url: str, full_page: bool = False) -> dict[str, Any]:
    """Synchronous version of take_screenshot."""
    return asyncio.run(take_screenshot(url, full_page))


async def extract_links(url: str, filter_pattern: str = "") -> str:
    """Extract all links from a webpage.

    Args:
        url: URL to extract links from
        filter_pattern: Optional regex pattern to filter links

    Returns:
        List of links found on the page
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "Playwright not installed - cannot extract links"

    try:
        browser = await _get_browser()
        page = await browser.new_page()

        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")

            links = await page.evaluate("""
                () => {
                    const links = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href;
                        const text = a.textContent.trim();
                        if (href && !href.startsWith('javascript:')) {
                            links.push({ href, text: text.substring(0, 100) });
                        }
                    });
                    return links;
                }
            """)

            # Filter if pattern provided
            if filter_pattern:
                import re

                pattern = re.compile(filter_pattern, re.IGNORECASE)
                links = [
                    link
                    for link in links
                    if pattern.search(link["href"]) or pattern.search(link["text"])
                ]

            output = f"=== Links from {url} ===\n"
            output += f"Found {len(links)} links"
            if filter_pattern:
                output += f" matching '{filter_pattern}'"
            output += "\n\n"

            for link in links[:50]:  # Limit to 50 links
                output += f"- [{link['text'][:50]}]({link['href']})\n"

            if len(links) > 50:
                output += f"\n... and {len(links) - 50} more links"

            return output

        finally:
            await page.close()

    except Exception as e:
        return f"Error extracting links: {e}"


def extract_links_sync(url: str, filter_pattern: str = "") -> str:
    """Synchronous version of extract_links."""
    return asyncio.run(extract_links(url, filter_pattern))


def get_browser_context(url: str) -> str:
    """Get webpage context for injection into agent prompts.

    This is designed for OpenHands-style context injection.

    Args:
        url: URL to fetch context from

    Returns:
        Formatted context string for agent prompts
    """
    try:
        content = fetch_webpage_sync(url)
        return f"## Web Page Context\n\n{content}"
    except Exception as e:
        return f"## Web Page Context\n\nError loading {url}: {e}"


# Competitive analysis helper
async def analyze_competitor_page(url: str) -> str:
    """Analyze a competitor's webpage for marketing insights.

    Args:
        url: Competitor URL to analyze

    Returns:
        Analysis of the page including key messaging, features, and CTAs
    """
    content = await fetch_webpage(url)

    return f"""=== Competitor Analysis: {url} ===

## Page Content
{content[:3000]}

## Analysis Instructions
Based on the above content, identify:
1. Key messaging and value propositions
2. Features highlighted
3. Calls to action (CTAs)
4. Target audience signals
5. Pricing information (if available)

Please provide your analysis.
"""


def analyze_competitor_page_sync(url: str) -> str:
    """Synchronous version of analyze_competitor_page."""
    return asyncio.run(analyze_competitor_page(url))
