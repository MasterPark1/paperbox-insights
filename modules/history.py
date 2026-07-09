"""리포트 스냅샷을 GitHub에 저장하고 불러온다."""
import json
import base64
import requests
import os
from datetime import datetime

import streamlit as st

_GITHUB_REPO = "MasterPark1/paperbox-insights"
_GITHUB_BRANCH = "main"
_HISTORY_DIR = "report_history"


def _github_token() -> str:
    try:
        for k in ("GITHUB_TOKEN", "github_token"):
            v = st.secrets.get(k)
            if v:
                return str(v)
    except Exception:
        pass
    return os.environ.get("GITHUB_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"token {_github_token()}",
        "Accept": "application/vnd.github.v3+json",
    }


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------

def _slim_data(data: dict) -> dict:
    """세션 data에서 저장할 항목만 추려 반환한다."""
    slim: dict = {}

    slim["financials"] = data.get("financials", {})
    slim["ottogi_ramen_detail"] = data.get("ottogi_ramen_detail")
    slim["insights"] = data.get("insights", {})
    slim["financial_comment"] = data.get("financial_comment", "")
    slim["news_analysis"] = data.get("news_analysis", {})
    slim["disclosure_analysis"] = data.get("disclosure_analysis", {})

    # 뉴스: 제목·링크·날짜만 보관 (description 제외해 용량 절감)
    news_slim = {}
    for company, items in (data.get("news") or {}).items():
        news_slim[company] = [
            {"title": n.get("title", ""), "link": n.get("link", ""),
             "pubDate": n.get("pubDate", "")}
            for n in (items or [])
        ]
    slim["news"] = news_slim

    # 공시: 제목·날짜·corp_code만 보관
    disc_slim = {}
    for company, items in (data.get("disclosures") or {}).items():
        disc_slim[company] = [
            {"report_nm": d.get("report_nm", ""), "rcept_dt": d.get("rcept_dt", ""),
             "rcept_no": d.get("rcept_no", ""), "corp_name": d.get("corp_name", "")}
            for d in (items or [])
        ]
    slim["disclosures"] = disc_slim

    return slim


def save_snapshot(data: dict, label: str = "") -> tuple[bool, str]:
    """리포트 데이터를 GitHub report_history/ 에 JSON으로 저장한다.

    Returns:
        (success, message)
    """
    token = _github_token()
    if not token:
        return False, "GitHub 토큰이 없어 저장하지 못했습니다."

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}.json"
    path = f"{_HISTORY_DIR}/{filename}"

    snapshot = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "label": label or ts,
        "data": _slim_data(data),
    }

    content_b64 = base64.b64encode(
        json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{path}"
    payload = {
        "message": f"리포트 스냅샷 저장: {ts}",
        "content": content_b64,
        "branch": _GITHUB_BRANCH,
    }
    r = requests.put(url, headers=_headers(), json=payload, timeout=20)
    if r.status_code in (200, 201):
        return True, filename
    return False, f"GitHub 저장 실패 ({r.status_code}): {r.text[:200]}"


# ---------------------------------------------------------------------------
# 목록
# ---------------------------------------------------------------------------

def list_snapshots() -> list[dict]:
    """report_history/ 디렉토리의 파일 목록을 최신순으로 반환한다.

    Returns:
        [{"filename": .., "path": .., "saved_at": .., "label": ..}, ...]
    """
    token = _github_token()
    if not token:
        return []

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{_HISTORY_DIR}"
    r = requests.get(url, headers=_headers(),
                     params={"ref": _GITHUB_BRANCH}, timeout=15)
    if r.status_code == 404:
        return []
    if r.status_code != 200:
        return []

    files = []
    for item in r.json():
        if not item.get("name", "").endswith(".json"):
            continue
        name = item["name"]
        # 파일명에서 날짜 추출 (YYYYMMDD_HHMMSS.json)
        try:
            dt = datetime.strptime(name.replace(".json", ""), "%Y%m%d_%H%M%S")
            display = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            display = name
        files.append({
            "filename": name,
            "path": item["path"],
            "sha": item.get("sha", ""),
            "display": display,
        })

    files.sort(key=lambda x: x["filename"], reverse=True)
    return files


# ---------------------------------------------------------------------------
# 불러오기
# ---------------------------------------------------------------------------

def load_snapshot(github_path: str) -> dict | None:
    """GitHub 경로에서 스냅샷 JSON을 읽어 data 딕셔너리를 반환한다."""
    token = _github_token()
    if not token:
        return None

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{github_path}"
    r = requests.get(url, headers=_headers(),
                     params={"ref": _GITHUB_BRANCH}, timeout=20)
    if r.status_code != 200:
        return None

    try:
        raw = base64.b64decode(r.json()["content"]).decode("utf-8")
        snapshot = json.loads(raw)
        return snapshot  # {"saved_at": .., "label": .., "data": {..}}
    except Exception:
        return None


def delete_snapshot(github_path: str, sha: str) -> tuple[bool, str]:
    """GitHub에서 스냅샷 파일을 삭제한다."""
    token = _github_token()
    if not token:
        return False, "GitHub 토큰이 없습니다."

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{github_path}"
    payload = {
        "message": f"리포트 스냅샷 삭제: {github_path}",
        "sha": sha,
        "branch": _GITHUB_BRANCH,
    }
    r = requests.delete(url, headers=_headers(), json=payload, timeout=15)
    if r.status_code == 200:
        return True, "삭제되었습니다."
    return False, f"삭제 실패 ({r.status_code})"
