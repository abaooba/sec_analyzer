import httpx
import trafilatura


def resolve_final_url(url: str) -> str:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True, verify=False) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            return str(response.url)
    except Exception:
        return url


def extract_article_text(url: str) -> tuple[str | None, str]:
    final_url = resolve_final_url(url)

    try:
        downloaded = trafilatura.fetch_url(final_url)
        if not downloaded:
            return None, final_url

        text = trafilatura.extract(downloaded)
        return text, final_url
    except Exception:
        return None, final_url