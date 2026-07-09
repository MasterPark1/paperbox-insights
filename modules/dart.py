"""
DART Open API를 통해 거래처별 공시자료 및 재무제표를 수집한다.
"""
import requests
from datetime import datetime, timedelta
import streamlit as st

REPRT_LABELS = {
    "11011": "연간",
    "11012": "반기",
    "11013": "1분기",
    "11014": "3분기",
}

# 연간 → 반기 → 1분기 → 3분기 순으로 시도 (안정적인 데이터 우선)
_REPRT_ORDER = ["11011", "11012", "11013", "11014"]

TARGET_ACCOUNTS = ["매출액", "영업이익", "법인세차감전순이익", "당기순이익"]


# ---------------------------------------------------------------------------
# Disclosures
# ---------------------------------------------------------------------------

def fetch_disclosures(corp_code: str, api_key: str, days: int = 7) -> list[dict]:
    """
    DART에서 특정 법인의 최근 공시 목록을 조회한다.

    Args:
        corp_code: DART 법인코드 (8자리 문자열)
        api_key: DART Open API 인증키
        days: 조회 기간(일). 오늘로부터 며칠 전까지의 공시를 포함할지 결정.

    Returns:
        공시 항목 리스트. 각 항목은 아래 키를 갖는 dict:
        - corp_name (str): 법인명
        - report_nm (str): 보고서명
        - rcept_dt (str): 접수일자 (YYYYMMDD)
        - rcept_no (str): 접수번호
        - url (str): DART 공시 URL
    """
    today = datetime.today()
    bgn_de = (today - timedelta(days=days)).strftime("%Y%m%d")
    end_de = today.strftime("%Y%m%d")

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_count": 20,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return []

    if data.get("status") != "000":
        return []

    results = []
    for item in data.get("list", []):
        rcept_no = item.get("rcept_no", "")
        results.append({
            "corp_name": item.get("corp_name", ""),
            "report_nm": item.get("report_nm", ""),
            "rcept_dt": item.get("rcept_dt", ""),
            "rcept_no": rcept_no,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })

    return results


def fetch_all_disclosures(companies: list, api_key: str, days: int = 7) -> dict:
    """
    모든 거래처의 공시 목록을 일괄 조회한다.

    Args:
        companies: COMPANIES 형식의 거래처 리스트
        api_key: DART Open API 인증키
        days: 조회 기간(일)

    Returns:
        {company_name: [disclosures]} 형태의 dict
    """
    result: dict[str, list[dict]] = {}
    for company in companies:
        name = company["name"]
        corp_code = company.get("dart_code", "")
        result[name] = fetch_disclosures(corp_code, api_key, days=days)
    return result


# ---------------------------------------------------------------------------
# Financials
# ---------------------------------------------------------------------------

def _parse_amount(value: str) -> int | None:
    """DART 재무데이터 금액 문자열을 정수(원)로 변환한다."""
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if cleaned in ("", "-", "―", "—"):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _fetch_single_financial(
    corp_code: str,
    api_key: str,
    bsns_year: str,
    reprt_code: str,
    fs_div: str = "CFS",
) -> list[dict] | None:
    """
    DART 단일회사 재무제표 API를 호출하고 결과 list를 반환한다.
    status가 '000'이 아니거나 요청 오류 시 None을 반환한다.
    """
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    if data.get("status") != "000":
        return None

    items = data.get("list")
    if not items:
        return None

    return items


def fetch_financials(corp_code: str, api_key: str) -> dict | None:
    """
    DART에서 특정 법인의 가장 최신 재무제표를 조회한다.

    분기(11013) → 반기(11012) → 3분기(11014) → 연간(11011) 순으로 시도하며,
    당해연도 데이터가 없으면 전년도를 시도한다. 연결재무제표(CFS) 우선,
    없으면 별도재무제표(OFS)로 폴백한다.

    Args:
        corp_code: DART 법인코드 (8자리)
        api_key: DART Open API 인증키

    Returns:
        재무 데이터 dict 또는 None (데이터 없음). dict 구조:
        {
            "period": "2024년 1분기",
            "reprt_code": "11013",
            "매출액": {"current": int, "previous": int},
            "영업이익": {"current": int, "previous": int},
            "법인세차감전순이익": {"current": int, "previous": int},
            "당기순이익": {"current": int, "previous": int},
        }
        값이 없는 항목은 None으로 채워진다.
    """
    today = datetime.today()
    current_year = today.year
    month = today.month

    # 현재 월 기준으로 조회할 보고서 1개만 결정
    if month in (3, 4):
        # 3~4월: 전년도 연간
        candidates = [(str(current_year - 1), "11011")]
    elif month in (5, 6, 7):
        # 5~7월: 당해 1분기
        candidates = [(str(current_year), "11013")]
    elif month in (8, 9, 10):
        # 8~10월: 당해 반기(2분기)
        candidates = [(str(current_year), "11012")]
    else:
        # 11~12월, 1~2월: 당해 3분기
        # 1~2월은 전년도 3분기 기준
        year = current_year if month >= 11 else current_year - 1
        candidates = [(str(year), "11014")]

    for bsns_year, reprt_code in candidates:
        items = None
        # 연결재무제표 우선
        for fs_div in ("CFS", "OFS"):
            items = _fetch_single_financial(
                corp_code, api_key, bsns_year, reprt_code, fs_div
            )
            if items:
                break

        if not items:
            continue

            # 계정과목별로 당기/전기 금액 추출
            account_map: dict[str, dict] = {}
            for row in items:
                acnt_nm = row.get("account_nm", "").strip()
                if acnt_nm not in TARGET_ACCOUNTS:
                    continue
                thstrm = _parse_amount(row.get("thstrm_amount", ""))
                frmtrm = _parse_amount(row.get("frmtrm_amount", ""))
                # 같은 계정이 여러 번 등장할 경우 첫 번째 값 사용
                if acnt_nm not in account_map:
                    account_map[acnt_nm] = {
                        "current": thstrm,
                        "previous": frmtrm,
                    }

            if not account_map:
                continue

            reprt_label = REPRT_LABELS.get(reprt_code, reprt_code)
            period_str = f"{bsns_year}년 {reprt_label}"

            result: dict = {
                "period": period_str,
                "reprt_code": reprt_code,
            }
            for acnt in TARGET_ACCOUNTS:
                result[acnt] = account_map.get(acnt, {"current": None, "previous": None})

            return result

    return None


def fetch_all_financials(companies: list, api_key: str) -> dict:
    """
    모든 거래처의 재무제표를 일괄 조회한다.

    Args:
        companies: COMPANIES 형식의 거래처 리스트
        api_key: DART Open API 인증키

    Returns:
        {company_name: financial_dict_or_None} 형태의 dict
    """
    result: dict[str, dict | None] = {}
    for company in companies:
        name = company["name"]
        corp_code = company.get("dart_code", "")
        result[name] = fetch_financials(corp_code, api_key)
    return result
