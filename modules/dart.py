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
            "bsns_year": bsns_year,
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


def _fetch_ottogi_xml(
    api_key: str,
    bsns_year: str | None = None,
    reprt_code: str | None = None,
) -> tuple[str, str, str] | None:
    """
    오뚜기 정기공시 XML과 기간 정보를 반환한다. (xml_content, period_year, report_nm)
    bsns_year + reprt_code가 주어지면 해당 보고서와 일치하는 XML을 검색한다.
    """
    OTTOGI_CORP_CODE = "00141529"
    today = datetime.today()

    # reprt_code → DART 목록 조회용 파라미터 매핑
    REPRT_TO_DETAIL_TY = {
        "11011": "A001",  # 사업보고서
        "11012": "A002",  # 반기보고서
        "11013": "A003",  # 분기보고서 (1분기)
        "11014": "A003",  # 분기보고서 (3분기)
    }

    params: dict = {
        "crtfc_key": api_key,
        "corp_code": OTTOGI_CORP_CODE,
        "page_count": 10,
    }

    if bsns_year and reprt_code:
        detail_ty = REPRT_TO_DETAIL_TY.get(reprt_code, "A001")
        # 사업보고서는 bsns_year 다음 해 3~4월에 공시되므로 범위 확장
        if reprt_code == "11011":
            params["bgn_de"] = f"{bsns_year}0101"
            params["end_de"] = f"{int(bsns_year) + 1}1231"
        else:
            params["bgn_de"] = f"{bsns_year}0101"
            params["end_de"] = f"{bsns_year}1231"
        params["pblntf_detail_ty"] = detail_ty
    else:
        params["bgn_de"] = f"{today.year - 1}0101"
        params["end_de"] = today.strftime("%Y%m%d")
        params["pblntf_ty"] = "A"

    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        filings = resp.json().get("list", [])
    except Exception:
        return None

    TARGET_REPORTS = ("사업보고서", "반기보고서", "분기보고서")
    relevant = [f for f in filings if any(t in f.get("report_nm", "") for t in TARGET_REPORTS)]
    if not relevant:
        return None

    filing = relevant[0]
    rcept_no = filing.get("rcept_no", "")
    rcept_dt = filing.get("rcept_dt", "")
    report_nm = filing.get("report_nm", "보고서")
    period_year = bsns_year if bsns_year else (rcept_dt[:4] if rcept_dt else str(today.year - 1))

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
        main_xml = next((f for f in xml_files if rcept_no in f), xml_files[0])
        xml_content = zf.read(main_xml).decode("utf-8", errors="ignore")
    except Exception:
        return None

    return xml_content, period_year, report_nm


def fetch_ottogi_ramen_financials(
    api_key: str,
    bsns_year: str | None = None,
    reprt_code: str | None = None,
) -> dict | None:
    """종속회사 오뚜기라면㈜ 요약 재무현황만 반환하는 편의 함수."""
    detail = fetch_ottogi_ramen_detail(api_key, bsns_year=bsns_year, reprt_code=reprt_code)
    if detail:
        return detail.get("financials")
    return None


def fetch_ottogi_ramen_detail(
    api_key: str,
    bsns_year: str | None = None,
    reprt_code: str | None = None,
) -> dict | None:
    """
    DART 보고서 XML에서 오뚜기라면㈜ 관련
    1) 종속회사별 요약 재무현황 테이블 행
    2) 사업의 개요 중 오뚜기라면(주) 관련 설명 텍스트
    를 함께 반환한다.
    bsns_year + reprt_code를 주면 오뚜기 본사 재무 데이터와 동일한 보고서를 사용한다.
    """
    result = _fetch_ottogi_xml(api_key, bsns_year=bsns_year, reprt_code=reprt_code)
    if not result:
        return None
    xml_content, period_year, report_nm = result

    def _to_int(s: str) -> int:
        return int(s.replace(",", ""))

    def _td_texts(tr_html: str) -> list[str]:
        """TR 블록 안의 모든 TD 텍스트(태그 제거)를 순서대로 반환한다."""
        tds = re.findall(r"<TD[^>]*>(.*?)</TD>", tr_html, re.DOTALL | re.IGNORECASE)
        return [_strip_tags(td).strip() for td in tds]

    # ── 1. 재무현황 테이블 파싱 ──────────────────────────────
    # TR 블록 전체를 찾아서 '오뚜기라면' 포함 행을 처리
    financials = None
    tr_blocks = re.findall(r"<TR[^>]*>.*?</TR>", xml_content, re.DOTALL | re.IGNORECASE)
    for tr in tr_blocks:
        if "오뚜기라면" not in tr:
            continue
        cells = _td_texts(tr)
        # 첫 셀: 회사명, 나머지 5셀: 자산/부채/자본/매출액/순이익 (숫자)
        if len(cells) < 6:
            continue
        # 숫자 셀이 4개 이상 있어야 재무 테이블 행으로 인정
        num_cells = [c for c in cells[1:] if re.fullmatch(r"[\d,\(\)\-]+", c.replace(" ", ""))]
        if len(num_cells) < 4:
            continue
        # 괄호로 감싼 음수 처리: (23,779,145) → -23779145
        def _parse_cell(s: str) -> int | None:
            s = s.strip().replace(",", "")
            if not s or s in ("-", "―", "—"):
                return None
            if s.startswith("(") and s.endswith(")"):
                try:
                    return -int(s[1:-1])
                except ValueError:
                    return None
            try:
                return int(s)
            except ValueError:
                return None

        nums = [_parse_cell(c) for c in cells[1:6]]
        if all(v is None for v in nums):
            continue
        financials = {
            "자산": nums[0] if len(nums) > 0 else None,
            "부채": nums[1] if len(nums) > 1 else None,
            "자본": nums[2] if len(nums) > 2 else None,
            "매출액": nums[3] if len(nums) > 3 else None,
            "분기순이익": nums[4] if len(nums) > 4 else None,
            "단위": "천원",
            "period": f"{period_year}년 연간",
        }
        break

    # ── 2. □ 오뚜기라면(주) 섹션 설명 파싱 ──────────────────
    # 보고서의 각 종속회사 설명 섹션은 "□ 회사명" 헤더로 시작한다.
    # XML에서 □+오뚜기라면 마커 위치를 찾고, 다음 □ 마커까지의 텍스트를 추출.
    overview_paragraphs: list[str] = []

    # □ 오뚜기라면 헤더 위치 탐색 (□ U+25A1 또는 ■ U+25A0)
    marker_pat = re.compile(r"[□■▣◆]\s*오뚜기라면")
    marker_m = marker_pat.search(xml_content)

    if marker_m:
        start = marker_m.start()
        # 다음 □ 마커 위치 (다른 회사 섹션 시작) 또는 최대 5000자
        next_marker = marker_pat.search(xml_content, start + 1)
        end = next_marker.start() if next_marker else min(start + 5000, len(xml_content))
        section_html = xml_content[start:end]

        # 섹션 내 <P> 태그 추출
        p_blocks = re.findall(r"<P[^>]*>(.*?)</P>", section_html, re.DOTALL | re.IGNORECASE)
        for block in p_blocks:
            text = _strip_tags(block).strip()
            if len(text) < 15:
                continue
            overview_paragraphs.append(text)

        # <P> 없으면 섹션 전체를 줄바꿈 기준으로 분할
        if not overview_paragraphs:
            plain = _strip_tags(section_html)
            for line in re.split(r"\n+", plain):
                line = line.strip()
                if len(line) >= 15:
                    overview_paragraphs.append(line)

    # □ 마커가 없으면 기존 방식 폴백: 서술형 <P> 단락에서 수집
    if not overview_paragraphs:
        p_blocks = re.findall(r"<P[^>]*>(.*?)</P>", xml_content, re.DOTALL | re.IGNORECASE)
        for block in p_blocks:
            if "오뚜기라면" not in block:
                continue
            text = _strip_tags(block).strip()
            if len(text) < 30:
                continue
            korean = len(re.findall(r"[가-힣]", text))
            if korean < 15:
                continue
            # 회사명 나열 문장 제외
            if len(re.findall(r"[㈜]", text)) >= 4 and len(text) < 300:
                continue
            overview_paragraphs.append(text)

    return {
        "financials": financials,
        "overview_paragraphs": overview_paragraphs[:10],
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
