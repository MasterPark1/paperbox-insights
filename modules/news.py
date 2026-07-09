"""
네이버 뉴스 Search API를 통해 거래처별 주간 뉴스를 수집한다.
"""
import re
import html
import requests
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import streamlit as st

COMPANIES = [
    {"name": "오뚜기",   "dart_code": "00141529", "keywords": ["오뚜기", "오뚜기라면"]},
    {"name": "삼양식품", "dart_code": "00126955", "keywords": ["삼양식품", "삼양라면"]},
    {"name": "농심",     "dart_code": "00108241", "keywords": ["농심", "농심라면"]},
    {"name": "팔도",     "dart_code": "00227643", "keywords": ["팔도", "팔도라면"]},
]


def _clean(text: str) -> str:
    """Strip HTML tags and unescape HTML entities from Naver news text."""
    return html.unescape(re.sub(r'<[^>]+>', '', text or ''))


def fetch_news(
    company: dict,
    client_id: str,
    client_secret: str,
    days: int = 7,
    max_items: int = 20,
) -> list[dict]:
    """
    Naver News Search API를 통해 특정 거래처의 최근 뉴스를 수집한다.

    Args:
        company: COMPANIES 리스트의 원소 dict (name, dart_code, keywords)
        client_id: Naver API Client ID
        client_secret: Naver API Client Secret
        days: 수집 기간(일). 오늘로부터 며칠 전까지의 기사를 포함할지 결정.
        max_items: 키워드당 최대 수집 건수 (Naver API display 파라미터)

    Returns:
        중복 제거된 뉴스 항목 리스트. 각 항목은 아래 키를 갖는 dict:
        - title (str): HTML 태그 제거된 제목
        - link (str): 기사 URL
        - description (str): HTML 태그 제거된 요약
        - pubDate (str): ISO 8601 형식의 발행일시
        - company_name (str): 거래처명
    """
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen_links: set[str] = set()
    results: list[dict] = []

    for keyword in company.get("keywords", []):
        params = {
            "query": keyword,
            "display": max_items,
            "sort": "date",
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            continue

        items = data.get("items", [])
        for item in items:
            link = item.get("link", "")
            if link in seen_links:
                continue

            raw_pub_date = item.get("pubDate", "")
            try:
                pub_dt = parsedate_to_datetime(raw_pub_date)
                # parsedate_to_datetime may return naive datetime for some formats;
                # ensure timezone-aware for comparison
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                # If date parsing fails, include the item anyway
                pub_dt = datetime.now(timezone.utc)

            if pub_dt < cutoff:
                continue

            seen_links.add(link)
            results.append({
                "title": _clean(item.get("title", "")),
                "link": link,
                "description": _clean(item.get("description", "")),
                "pubDate": pub_dt.isoformat(),
                "company_name": company["name"],
            })

    # Sort by pubDate descending (most recent first)
    results.sort(key=lambda x: x["pubDate"], reverse=True)
    return results


def fetch_all_news(
    companies: list,
    client_id: str,
    client_secret: str,
    days: int = 7,
) -> dict:
    """
    모든 거래처의 뉴스를 일괄 수집한다.

    Args:
        companies: COMPANIES 형식의 거래처 리스트
        client_id: Naver API Client ID
        client_secret: Naver API Client Secret
        days: 수집 기간(일)

    Returns:
        {company_name: [news_items]} 형태의 dict
    """
    result: dict[str, list[dict]] = {}
    for company in companies:
        name = company["name"]
        result[name] = fetch_news(company, client_id, client_secret, days=days)
    return result
