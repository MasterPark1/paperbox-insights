"""
DART Open API를 통해 거래처별 공시자료 및 재무제표를 수집한다.
"""
import io
import re
import zipfile
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

# API 반환 계정명 → 표준 계정명 매핑 (띄어쓰기·괄호 표기 차이 처리)
_ACCOUNT_ALIAS = {
    "법인세차감전 순이익": "법인세차감전순이익",
    "당기순이익(손실)": "당기순이익",
    "당기순손실": "당기순이익",
}


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
            acnt_nm = _ACCOUNT_ALIAS.get(acnt_nm, acnt_nm)
            if acnt_nm not in TARGET_ACCOUNTS:
                continue
            thstrm = _parse_amount(row.get("thstrm_amount", ""))
            frmtrm = _parse_amount(row.get("frmtrm_amount", ""))
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


def _strip_tags(html: str) -> str:
    """HTML 태그를 제거하고 공백을 정리한다."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _fetch_ottogi_xml(api_key: str) -> tuple[str, str, str] | None:
    """오뚜기 사업보고서 XML 내용과 기간 정보를 반환한다. (xml_content, period_year, report_nm)"""
    OTTOGI_CORP_CODE = "00141529"
    today = datetime.today()

    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={
                "crtfc_key": api_key,
                "corp_code": OTTOGI_CORP_CODE,
                "bgn_de": f"{today.year - 1}0101",
                "end_de": today.strftime("%Y%m%d"),
                "pblntf_detail_ty": "A001",
                "page_count": 5,
            },
            timeout=10,
        )
        resp.raise_for_status()
        filings = resp.json().get("list", [])
    except Exception:
        return None

    if not filings:
        return None

    rcept_no = filings[0].get("rcept_no", "")
    rcept_dt = filings[0].get("rcept_dt", "")
    report_nm = filings[0].get("report_nm", "사업보고서")
    period_year = rcept_dt[:4] if rcept_dt else str(today.year - 1)

    try:
        zip_resp = requests.get(
            "https://opendart.fss.or.kr/api/document.xml",
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=30,
        )
        zip_resp.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(zip_resp.content))
        xml_files = [f for f in zf.namelist() if f.endswith(".xml")]
        if not xml_files:
            return None
        xml_content = zf.read(xml_files[0]).decode("utf-8", errors="ignore")
    except Exception:
        return None

    return xml_content, period_year, report_nm


def fetch_ottogi_ramen_financials(api_key: str) -> dict | None:
    """
    DART 사업보고서 XML에서 종속회사 오뚜기라면㈜의 요약 재무현황을 파싱한다.
    """
    result = _fetch_ottogi_xml(api_key)
    if not result:
        return None
    xml_content, period_year, _ = result

    pattern = (
        r"오뚜기라면[㈜\(주\)]</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>\(?([0-9,]+)\)?</TD>"
    )
    m = re.search(pattern, xml_content)
    if not m:
        return None

    def _to_int(s: str) -> int:
        return int(s.replace(",", ""))

    return {
        "자산": _to_int(m.group(1)),
        "부채": _to_int(m.group(2)),
        "자본": _to_int(m.group(3)),
        "매출액": _to_int(m.group(4)),
        "분기순이익": _to_int(m.group(5)),
        "단위": "천원",
        "period": f"{period_year}년 연간",
    }


def fetch_ottogi_ramen_detail(api_key: str) -> dict | None:
    """
    DART 사업보고서 XML에서 오뚜기라면㈜ 관련
    1) 종속회사별 요약 재무현황 테이블 행
    2) 사업의 개요 중 오뚜기라면(주) 관련 설명 텍스트
    를 함께 반환한다.

    Returns:
        {
            "financials": { 자산, 부채, 자본, 매출액, 분기순이익, 단위, period },
            "overview_paragraphs": [ str, ... ],   # 오뚜기라면 관련 설명 단락 목록
            "report_nm": str,
            "period": str,
        }
        또는 None
    """
    result = _fetch_ottogi_xml(api_key)
    if not result:
        return None
    xml_content, period_year, report_nm = result

    # ── 1. 재무현황 테이블 파싱 ──────────────────────────────
    fin_pattern = (
        r"오뚜기라면[㈜\(주\)]</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>([\d,]+)</TD>\s*"
        r"<TD[^>]*>\(?([0-9,]+)\)?</TD>"
    )
    fin_m = re.search(fin_pattern, xml_content)

    def _to_int(s: str) -> int:
        return int(s.replace(",", ""))

    financials = None
    if fin_m:
        financials = {
            "자산": _to_int(fin_m.group(1)),
            "부채": _to_int(fin_m.group(2)),
            "자본": _to_int(fin_m.group(3)),
            "매출액": _to_int(fin_m.group(4)),
            "분기순이익": _to_int(fin_m.group(5)),
            "단위": "천원",
            "period": f"{period_year}년 연간",
        }

    # ── 2. 사업의 개요 오뚜기라면 설명 파싱 ─────────────────
    # <P> 또는 <TD> 안에 "오뚜기라면"이 포함된 텍스트 단락을 수집
    # 단, 숫자 위주(테이블 셀)는 제외하고 한글 설명문만 추출
    overview_paragraphs: list[str] = []
    seen: set[str] = set()

    # 방법1: <P ...>...</P> 블록에서 오뚜기라면 포함 단락
    p_blocks = re.findall(r"<P[^>]*>(.*?)</P>", xml_content, re.DOTALL | re.IGNORECASE)
    for block in p_blocks:
        if "오뚜기라면" not in block:
            continue
        text = _strip_tags(block).strip()
        # 너무 짧거나(단순 회사명 언급), 숫자 위주 셀이면 제외
        if len(text) < 20:
            continue
        # 한글 비율이 낮으면(숫자 테이블) 제외
        korean_chars = len(re.findall(r"[가-힣]", text))
        if korean_chars < 10:
            continue
        key = text[:60]
        if key not in seen:
            seen.add(key)
            overview_paragraphs.append(text)

    # 방법2: P 태그가 없으면 SPAN·DIV 블록도 시도
    if not overview_paragraphs:
        span_blocks = re.findall(
            r"<(?:SPAN|DIV|TD)[^>]*>(.*?)</(?:SPAN|DIV|TD)>",
            xml_content, re.DOTALL | re.IGNORECASE,
        )
        for block in span_blocks:
            if "오뚜기라면" not in block:
                continue
            text = _strip_tags(block).strip()
            if len(text) < 30:
                continue
            korean_chars = len(re.findall(r"[가-힣]", text))
            if korean_chars < 15:
                continue
            key = text[:60]
            if key not in seen:
                seen.add(key)
                overview_paragraphs.append(text)

    # 최대 10개 단락으로 제한
    overview_paragraphs = overview_paragraphs[:10]

    return {
        "financials": financials,
        "overview_paragraphs": overview_paragraphs,
        "report_nm": report_nm,
        "period": f"{period_year}년 연간",
    }


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
