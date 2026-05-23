import httpx

USER_AGENT = "rssx/0.1 (+https://github.com/d-issy/rssx)"


def fetch_url(
    url: str, etag: str | None = None, last_modified: str | None = None
) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        return client.get(url)
