"""Read-only MCP tools for public Zhengzhou University information."""

import ipaddress
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mcp.server.fastmcp import FastMCP

from config import (
    ZZU_HTTP_TIMEOUT_SECONDS,
    ZZU_MAX_REDIRECTS,
    ZZU_MAX_RESPONSE_BYTES,
    ZZU_OFFICIAL_DOMAIN,
    ZZU_OFFICIAL_SOURCES,
    ZZU_SEARCH_URL,
)


_IGNORED_TAGS = {"script", "style", "noscript", "svg"}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
TOOL_NAMES = (
    "search_zzu_official_site",
    "read_zzu_official_page",
    "list_zzu_official_sources",
)

mcp = FastMCP(
    "郑州大学只读校园资料",
    instructions="仅查询郑州大学官网公开资料，不执行写入或提交操作。",
)


def validate_official_url(raw_url: str) -> str:
    """Validate and normalize a public Zhengzhou University page URL."""

    parsed = urlsplit(raw_url.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("只支持郑州大学公开网页地址")
    if parsed.username or parsed.password:
        raise ValueError("网页地址不符合只读资料访问规则")

    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("网页地址端口无效") from error

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("不允许使用 IP 地址访问")

    if hostname != ZZU_OFFICIAL_DOMAIN and not hostname.endswith(
        f".{ZZU_OFFICIAL_DOMAIN}"
    ):
        raise ValueError("只允许访问郑州大学官方域名")

    default_port = 80 if parsed.scheme == "http" else 443
    if port not in {None, default_port}:
        raise ValueError("不允许使用非默认端口")

    authority = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in _IGNORED_TAGS:
            self._ignored_depth += 1
        elif normalized == "title" and not self._ignored_depth:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in _IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif normalized == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    def result(self) -> dict[str, str]:
        return {
            "title": _normalize_text(" ".join(self._title_parts)),
            "text": _normalize_text(" ".join(self._text_parts)),
        }


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_page_text(html: str) -> dict[str, str]:
    """Extract readable title and text from an HTML document."""

    parser = _ReadableTextParser()
    parser.feed(html)
    parser.close()
    return parser.result()


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        del request, fp, code, msg, headers, newurl
        return None


def _open_request(request: Request, timeout: float):
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def _decode_response(body: bytes, charset: str | None) -> str:
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _fetch_html(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    opener: Callable[[Request, float], object] | None = None,
) -> tuple[str, str]:
    current_url = validate_official_url(url)
    request_opener = opener or _open_request

    for redirect_count in range(ZZU_MAX_REDIRECTS + 1):
        request = Request(
            current_url,
            data=data if method == "POST" else None,
            method=method,
            headers={"User-Agent": "YouHuaShuo-ZZU-ReadOnly-MCP/1.0"},
        )
        try:
            response = request_opener(request, ZZU_HTTP_TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        except URLError as error:
            raise ValueError("郑州大学官网暂时无法访问") from error

        status = getattr(response, "status", getattr(response, "code", 200))
        if status in _REDIRECT_STATUS_CODES:
            location = response.headers.get("Location")
            if not location:
                raise ValueError("官网页面重定向地址无效")
            if redirect_count >= ZZU_MAX_REDIRECTS:
                raise ValueError("官网页面重定向次数过多")
            current_url = validate_official_url(urljoin(current_url, location))
            method = "GET"
            data = None
            continue
        if not 200 <= status < 300:
            raise ValueError("郑州大学官网页面暂时不可用")

        content_type = response.headers.get_content_type()
        if content_type != "text/html":
            raise ValueError("只支持读取官网 HTML 页面")
        body = response.read(ZZU_MAX_RESPONSE_BYTES + 1)
        if len(body) > ZZU_MAX_RESPONSE_BYTES:
            raise ValueError("官网页面内容过大")
        return _decode_response(body, response.headers.get_content_charset()), current_url

    raise ValueError("官网页面重定向次数过多")


def fetch_official_page(
    url: str, *, opener: Callable[[Request, float], object] | None = None
) -> dict[str, str]:
    """Read one public official HTML page without allowing side effects."""

    html, source_url = _fetch_html(url, opener=opener)
    page = extract_page_text(html)
    return {
        "source_url": source_url,
        "title": page["title"],
        "text": page["text"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


class _OfficialLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._active_href: str | None = None
        self._text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._active_href = dict(attrs).get("href")
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._active_href:
            return
        self.links.append((self._active_href, _normalize_text(" ".join(self._text_parts))))
        self._active_href = None
        self._text_parts = []


def _extract_official_links(html: str, base_url: str) -> list[dict[str, str]]:
    parser = _OfficialLinkParser()
    parser.feed(html)
    parser.close()
    links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for href, title in parser.links:
        if not title:
            continue
        try:
            source_url = validate_official_url(urljoin(base_url, href))
        except ValueError:
            continue
        if source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        links.append({"title": title, "source_url": source_url})
        if len(links) == 10:
            break
    return links


@mcp.tool(description="搜索郑州大学官网公开资料，仅返回官方链接。")
def search_zzu_official_site(query: str) -> dict[str, object]:
    """Search public Zhengzhou University pages by a user-provided keyword."""

    keyword = query.strip()
    if not keyword:
        raise ValueError("搜索关键词不能为空")
    payload = urlencode(
        {
            "showkeycode": keyword,
            "lucenenewssearchkey": "",
            "_lucenesearchtype": "1",
            "searchScope": "0",
        }
    ).encode("utf-8")
    html, source_url = _fetch_html(ZZU_SEARCH_URL, method="POST", data=payload)
    return {
        "query": keyword,
        "source_url": source_url,
        "results": _extract_official_links(html, source_url),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool(description="读取郑州大学官网允许域名内的公开 HTML 页面。")
def read_zzu_official_page(url: str) -> dict[str, str]:
    """Read a public Zhengzhou University page."""

    return fetch_official_page(url)


@mcp.tool(description="列出郑州大学常用官方资料入口。")
def list_zzu_official_sources() -> dict[str, object]:
    """List curated public Zhengzhou University entry points."""

    return {
        "sources": [
            {"name": name, "source_url": url, "description": description}
            for name, url, description in ZZU_OFFICIAL_SOURCES
        ]
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
