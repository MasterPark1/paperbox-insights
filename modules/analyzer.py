"""
OpenAI API (gpt-4o-mini)를 사용해 뉴스·공시·재무 데이터를 분석하고 인사이트를 생성한다.
"""
import json
from openai import OpenAI, AuthenticationError, RateLimitError, APIError
import streamlit as st

_MODEL = "gpt-4o-mini"

_ANALYST_SYSTEM = (
    "당신은 라면 제조사에 종이용기(컵라면 용기 등)를 납품하는 B2B 영업 분석가입니다. "
    "한국어로 답변하세요."
)
_STRATEGIST_SYSTEM = (
    "당신은 라면 제조사에 종이용기(컵라면 용기 등)를 납품하는 B2B 영업 전략가입니다. "
    "한국어로 답변하세요."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def _chat_json(client: OpenAI, system: str, user: str) -> dict:
    """JSON 응답을 요구하는 ChatCompletion 호출. 파싱된 dict를 반환한다."""
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _chat_text(client: OpenAI, system: str, user: str) -> str:
    """평문 응답을 반환하는 ChatCompletion 호출."""
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()


def _format_news_text(news_items: list[dict]) -> str:
    """뉴스 항목을 프롬프트용 텍스트로 변환한다."""
    lines = []
    for i, item in enumerate(news_items, 1):
        lines.append(
            f"{i}. [{item.get('pubDate', '')[:10]}] {item.get('title', '')}\n"
            f"   {item.get('description', '')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# analyze_news
# ---------------------------------------------------------------------------

_NEWS_DEFAULT = {
    "summary": "뉴스 데이터 없음",
    "sentiment": "중립",
    "impact": "",
    "top_issues": [],
    "importance": "보통",
}

_NEWS_ERROR_DEFAULT = {
    "summary": "분석 실패",
    "sentiment": "중립",
    "impact": "",
    "top_issues": [],
    "importance": "보통",
}


def analyze_news(company_name: str, news_items: list[dict], api_key: str) -> dict:
    """
    거래처 뉴스를 분석하여 요약·감성·영향도 등을 반환한다.

    Args:
        company_name: 거래처명
        news_items: fetch_news()가 반환한 뉴스 항목 리스트
        api_key: OpenAI API 키

    Returns:
        dict with keys:
        - summary (str): 3줄 요약
        - sentiment (str): 긍정/부정/중립
        - impact (str): 거래처 사업 영향 2~3문장
        - top_issues (list[str]): 주요 이슈 3개
        - importance (str): 높음/보통/낮음
    """
    if not news_items:
        return dict(_NEWS_DEFAULT)

    client = _make_client(api_key)
    news_text = _format_news_text(news_items)

    user_prompt = (
        f"{company_name} 관련 최근 뉴스 {len(news_items)}건을 분석하여 "
        f"다음 JSON 형식으로 반환하세요:\n{news_text}\n\n"
        "JSON 키: "
        "summary(3줄 요약 문자열), "
        "sentiment(긍정/부정/중립), "
        "impact(거래처 사업 영향 2~3문장), "
        "top_issues(주요이슈 문자열 리스트 3개), "
        "importance(높음/보통/낮음)"
    )

    try:
        result = _chat_json(client, _ANALYST_SYSTEM, user_prompt)
        # Ensure all expected keys exist with sensible fallbacks
        return {
            "summary": result.get("summary", _NEWS_ERROR_DEFAULT["summary"]),
            "sentiment": result.get("sentiment", "중립"),
            "impact": result.get("impact", ""),
            "top_issues": result.get("top_issues", []),
            "importance": result.get("importance", "보통"),
        }
    except (AuthenticationError, RateLimitError, APIError, json.JSONDecodeError, Exception):
        return dict(_NEWS_ERROR_DEFAULT)


# ---------------------------------------------------------------------------
# analyze_disclosures
# ---------------------------------------------------------------------------

_DISC_DEFAULT = {
    "summary": "공시 데이터 없음",
    "impact": "",
    "grade": "중",
    "special_notes": "",
}

_DISC_ERROR_DEFAULT = {
    "summary": "분석 실패",
    "impact": "",
    "grade": "중",
    "special_notes": "",
}


def analyze_disclosures(
    company_name: str, disclosures: list[dict], api_key: str
) -> dict:
    """
    거래처 공시자료를 분석하여 재무경영 영향 및 등급을 반환한다.

    Args:
        company_name: 거래처명
        disclosures: fetch_disclosures()가 반환한 공시 항목 리스트
        api_key: OpenAI API 키

    Returns:
        dict with keys:
        - summary (str): 3~5문장 요약
        - impact (str): 재무·경영 영향
        - grade (str): 상/중/하
        - special_notes (str): 특이사항
    """
    if not disclosures:
        return dict(_DISC_DEFAULT)

    client = _make_client(api_key)

    disc_lines = []
    for i, d in enumerate(disclosures, 1):
        disc_lines.append(
            f"{i}. [{d.get('rcept_dt', '')}] {d.get('report_nm', '')} "
            f"(법인명: {d.get('corp_name', '')})"
        )
    disc_text = "\n".join(disc_lines)

    user_prompt = (
        f"{company_name}의 최근 공시자료 {len(disclosures)}건을 분석하여 "
        "다음 JSON 형식으로 반환하세요:\n"
        f"{disc_text}\n\n"
        "JSON 키: "
        "summary(3~5문장 요약 문자열), "
        "impact(재무·경영 영향 서술), "
        "grade(상/중/하 — 공시 중요도 평가), "
        "special_notes(특이사항 문자열)"
    )

    try:
        result = _chat_json(client, _ANALYST_SYSTEM, user_prompt)
        return {
            "summary": result.get("summary", _DISC_ERROR_DEFAULT["summary"]),
            "impact": result.get("impact", ""),
            "grade": result.get("grade", "중"),
            "special_notes": result.get("special_notes", ""),
        }
    except (AuthenticationError, RateLimitError, APIError, json.JSONDecodeError, Exception):
        return dict(_DISC_ERROR_DEFAULT)


# ---------------------------------------------------------------------------
# analyze_financials
# ---------------------------------------------------------------------------

def _format_financial_table(all_financials: dict) -> str:
    """재무 데이터를 프롬프트용 텍스트 테이블로 변환한다."""
    from dart import TARGET_ACCOUNTS  # lazy import to avoid circular deps at module level

    lines = ["거래처 재무 현황 (단위: 백만원, 반올림)"]
    lines.append("-" * 60)

    for company_name, fin in all_financials.items():
        if fin is None:
            lines.append(f"\n[{company_name}] 재무 데이터 없음")
            continue

        period = fin.get("period", "기간 미상")
        lines.append(f"\n[{company_name}] {period}")

        for acnt in TARGET_ACCOUNTS:
            values = fin.get(acnt, {})
            if isinstance(values, dict):
                cur = values.get("current")
                prv = values.get("previous")
                cur_str = f"{cur // 1_000_000:,}백만원" if cur is not None else "N/A"
                prv_str = f"{prv // 1_000_000:,}백만원" if prv is not None else "N/A"
                lines.append(f"  {acnt}: 당기 {cur_str} / 전기 {prv_str}")
            else:
                lines.append(f"  {acnt}: N/A")

    lines.append("-" * 60)
    return "\n".join(lines)


def analyze_financials(all_financials: dict, api_key: str) -> str:
    """
    전체 거래처의 재무 데이터를 종합 분석한 코멘트를 반환한다.

    Args:
        all_financials: fetch_all_financials()가 반환한 {company_name: financial_dict} dict
        api_key: OpenAI API 키

    Returns:
        종합 분석 코멘트 문자열 (300자 이내)
    """
    try:
        # Try importing TARGET_ACCOUNTS from dart; fall back to hardcoded list
        try:
            from modules.dart import TARGET_ACCOUNTS as _ta
        except ImportError:
            try:
                from dart import TARGET_ACCOUNTS as _ta
            except ImportError:
                _ta = ["매출액", "영업이익", "법인세차감전순이익", "당기순이익"]

        lines = ["거래처 재무 현황 (단위: 백만원)"]
        lines.append("-" * 60)
        for company_name, fin in all_financials.items():
            if fin is None:
                lines.append(f"\n[{company_name}] 재무 데이터 없음")
                continue
            period = fin.get("period", "기간 미상")
            lines.append(f"\n[{company_name}] {period}")
            for acnt in _ta:
                values = fin.get(acnt, {})
                if isinstance(values, dict):
                    cur = values.get("current")
                    prv = values.get("previous")
                    cur_str = f"{cur // 1_000_000:,}백만원" if cur is not None else "N/A"
                    prv_str = f"{prv // 1_000_000:,}백만원" if prv is not None else "N/A"
                    lines.append(f"  {acnt}: 당기 {cur_str} / 전기 {prv_str}")
                else:
                    lines.append(f"  {acnt}: N/A")
        lines.append("-" * 60)
        fin_text = "\n".join(lines)

        client = _make_client(api_key)
        user_prompt = (
            "아래는 라면 제조사 4개사의 재무 현황입니다. "
            "종이용기(컵라면 용기) 공급사 관점에서 각 거래처의 재무 성과를 종합 분석하고, "
            "발주 여력 및 영업 우선순위에 대한 코멘트를 300자 이내로 작성하세요.\n\n"
            f"{fin_text}"
        )

        return _chat_text(client, _ANALYST_SYSTEM, user_prompt)

    except (AuthenticationError, RateLimitError, APIError, Exception):
        return "재무 분석에 실패했습니다."


# ---------------------------------------------------------------------------
# generate_insight
# ---------------------------------------------------------------------------

_INSIGHT_DEFAULT = {
    "order_forecast": "분석 데이터 부족",
    "risks": [],
    "opportunities": [],
    "strategy": "",
    "priority": "C",
}

_INSIGHT_ERROR_DEFAULT = {
    "order_forecast": "분석 실패",
    "risks": [],
    "opportunities": [],
    "strategy": "",
    "priority": "C",
}


def generate_insight(
    company_name: str,
    news_analysis: dict,
    disclosure_analysis: dict,
    financial_data: dict | None,
    api_key: str,
    subsidiary_ramen: dict | None = None,
) -> dict:
    """
    뉴스 분석·공시 분석·재무 데이터를 종합하여 영업 인사이트를 생성한다.

    Args:
        company_name: 거래처명
        news_analysis: analyze_news() 반환값
        disclosure_analysis: analyze_disclosures() 반환값
        financial_data: fetch_financials() 반환값 (None 가능)
        api_key: OpenAI API 키

    Returns:
        dict with keys:
        - order_forecast (str): 발주 가능성 전망
        - risks (list[str]): 리스크 요인 리스트
        - opportunities (list[str]): 기회 요인 리스트
        - strategy (str): 대응 전략 2~3문장
        - priority (str): A/B/C 영업 우선순위
    """
    client = _make_client(api_key)

    # Build context string
    ctx_parts = [f"=== {company_name} 종합 분석 컨텍스트 ===\n"]

    # News context
    ctx_parts.append(
        f"[뉴스 분석]\n"
        f"요약: {news_analysis.get('summary', 'N/A')}\n"
        f"감성: {news_analysis.get('sentiment', 'N/A')}\n"
        f"사업 영향: {news_analysis.get('impact', 'N/A')}\n"
        f"주요 이슈: {', '.join(news_analysis.get('top_issues', []))}\n"
        f"중요도: {news_analysis.get('importance', 'N/A')}\n"
    )

    # Disclosure context
    ctx_parts.append(
        f"[공시 분석]\n"
        f"요약: {disclosure_analysis.get('summary', 'N/A')}\n"
        f"재무·경영 영향: {disclosure_analysis.get('impact', 'N/A')}\n"
        f"등급: {disclosure_analysis.get('grade', 'N/A')}\n"
        f"특이사항: {disclosure_analysis.get('special_notes', 'N/A')}\n"
    )

    # Financial context
    if financial_data:
        try:
            from modules.dart import TARGET_ACCOUNTS as _ta
        except ImportError:
            try:
                from dart import TARGET_ACCOUNTS as _ta
            except ImportError:
                _ta = ["매출액", "영업이익", "법인세차감전순이익", "당기순이익"]

        fin_lines = [f"[재무 데이터] {financial_data.get('period', '')}"]
        for acnt in _ta:
            values = financial_data.get(acnt, {})
            if isinstance(values, dict):
                cur = values.get("current")
                prv = values.get("previous")
                cur_str = f"{cur // 1_000_000:,}백만원" if cur is not None else "N/A"
                prv_str = f"{prv // 1_000_000:,}백만원" if prv is not None else "N/A"
                fin_lines.append(f"  {acnt}: 당기 {cur_str} / 전기 {prv_str}")
            else:
                fin_lines.append(f"  {acnt}: N/A")
        ctx_parts.append("\n".join(fin_lines) + "\n")
    else:
        ctx_parts.append("[재무 데이터] 없음\n")

    # 오뚜기라면㈜ 종속회사 재무 데이터
    if subsidiary_ramen:
        unit = subsidiary_ramen.get("단위", "천원")
        period = subsidiary_ramen.get("period", "")
        rev = subsidiary_ramen.get("매출액")
        net = subsidiary_ramen.get("분기순이익")
        assets = subsidiary_ramen.get("자산")
        rev_str = f"{rev // 1_000:,}백만원" if rev is not None else "N/A"
        net_str = f"{net // 1_000:,}백만원" if net is not None else "N/A"
        assets_str = f"{assets // 1_000:,}백만원" if assets is not None else "N/A"
        ctx_parts.append(
            f"[오뚜기라면㈜ 종속회사 요약재무 ({period}, 단위:{unit})]\n"
            f"  자산: {assets_str} / 매출액: {rev_str} / 순이익: {net_str}\n"
        )

    context = "\n".join(ctx_parts)

    # 라면 부문 비중 언급이 필요한 회사 목록
    ramen_focus_companies = ["오뚜기", "농심"]
    ramen_instruction = ""
    if any(c in company_name for c in ramen_focus_companies):
        ramen_instruction = (
            f"\n\n특히 {company_name}의 전체 매출 중 라면 부문이 차지하는 비중과 "
            "최근 라면 부문의 동향(신제품, 수출, 시장점유율 변화 등)을 "
            "strategy 및 opportunities 항목에 반드시 언급하세요."
        )

    user_prompt = (
        f"{context}\n"
        f"위 정보를 바탕으로 {company_name}에 대한 영업 전략 인사이트를 "
        "다음 JSON 형식으로 반환하세요:\n"
        "JSON 키: "
        "order_forecast(발주 가능성 전망 문자열), "
        "risks(리스크 요인 문자열 리스트), "
        "opportunities(기회 요인 문자열 리스트), "
        "strategy(대응 전략 2~3문장 문자열), "
        "priority(A/B/C 영업 우선순위 — A가 최우선)"
        f"{ramen_instruction}"
    )

    try:
        result = _chat_json(client, _STRATEGIST_SYSTEM, user_prompt)
        return {
            "order_forecast": result.get("order_forecast", _INSIGHT_ERROR_DEFAULT["order_forecast"]),
            "risks": result.get("risks", []),
            "opportunities": result.get("opportunities", []),
            "strategy": result.get("strategy", ""),
            "priority": result.get("priority", "C"),
        }
    except (AuthenticationError, RateLimitError, APIError, json.JSONDecodeError, Exception):
        return dict(_INSIGHT_ERROR_DEFAULT)
