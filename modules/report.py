"""통합 리포트 HTML을 생성하고 파일로 저장한다."""
import os
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
PRIMARY = "#002271"
PRIMARY_CONTAINER = "#203a89"
SECONDARY = "#006e1d"
BACKGROUND = "#f4f7f9"
SURFACE = "#ffffff"
BORDER = "#E5E5E5"
TEXT = "#212529"
MUTED = "#666666"
SUCCESS = "#28A745"
DANGER = "#DC3545"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_억(won: int | None) -> str:
    if won is None:
        return "N/A"
    return f"{won / 100_000_000:.1f}억원"


def _pct_change(current: int | None, previous: int | None) -> str:
    if current is None or previous is None or previous == 0:
        return "N/A"
    pct = (current - previous) / abs(previous) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _pct_color(current: int | None, previous: int | None) -> str:
    if current is None or previous is None or previous == 0:
        return TEXT
    return SUCCESS if current >= previous else DANGER


def _op_margin(revenue: int | None, op_income: int | None) -> str:
    if revenue is None or op_income is None or revenue == 0:
        return "N/A"
    pct = op_income / revenue * 100
    return f"{pct:.1f}%"


def _priority_color(priority: str | None) -> str:
    mapping = {
        "높음": DANGER,
        "중간": "#FFA500",
        "낮음": SECONDARY,
        "high": DANGER,
        "medium": "#FFA500",
        "low": SECONDARY,
    }
    return mapping.get(str(priority).lower() if priority else "", MUTED)


def _sentiment_color(sentiment: str | None) -> str:
    if not sentiment:
        return MUTED
    s = sentiment.lower()
    if any(k in s for k in ("긍정", "positive", "good")):
        return SUCCESS
    if any(k in s for k in ("부정", "negative", "bad")):
        return DANGER
    return "#FFA500"


def _grade_color(grade: str | None) -> str:
    if not grade:
        return MUTED
    g = grade.upper()
    if g in ("A", "A+", "AA", "AAA", "S"):
        return SUCCESS
    if g in ("B", "B+", "BB"):
        return "#FFA500"
    return DANGER


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'background:{color};color:#fff;font-size:12px;font-weight:600;">{text}</span>'
    )


def _card(title: str, body: str, accent: str = PRIMARY) -> str:
    return f"""
<div style="background:{SURFACE};border:1px solid {BORDER};border-left:4px solid {accent};
     border-radius:6px;padding:16px 20px;margin-bottom:14px;">
  <div style="font-weight:700;font-size:14px;color:{accent};margin-bottom:10px;">{title}</div>
  {body}
</div>"""


def _bullet_list(items: list) -> str:
    if not items:
        return '<p style="color:{MUTED};font-size:13px;">해당 없음</p>'
    lis = "".join(
        f'<li style="margin-bottom:4px;font-size:13px;color:{TEXT};">{item}</li>'
        for item in items
    )
    return f'<ul style="margin:4px 0 0 18px;padding:0;">{lis}</ul>'


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_head(days: int) -> str:
    today = datetime.now()
    start = today - timedelta(days=days)
    period = f"{start.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}"
    generated = today.strftime("%Y-%m-%d %H:%M:%S")
    return f"""
<div style="background:linear-gradient(135deg,{PRIMARY} 0%,{PRIMARY_CONTAINER} 100%);
     color:#fff;padding:32px 40px;border-radius:8px 8px 0 0;">
  <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:0.8;
       margin-bottom:6px;">PaperBox Insights</div>
  <h1 style="margin:0 0 10px 0;font-size:24px;font-weight:700;">
    주간 거래처 분석 리포트
  </h1>
  <div style="font-size:13px;opacity:0.85;">
    분석기간: {period} &nbsp;|&nbsp; 생성일시: {generated}
  </div>
</div>"""


def _build_financials_section(data: dict) -> str:
    financials = data.get("financials", {})
    financial_comment = data.get("financial_comment", "")

    rows = []
    for company, fin in financials.items():
        if fin is None:
            rows.append(
                f"<tr>"
                f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};font-weight:600;">{company}</td>'
                f'<td colspan="5" style="padding:10px 14px;border-bottom:1px solid {BORDER};'
                f'color:{MUTED};font-style:italic;">재무 데이터 없음</td>'
                f"</tr>"
            )
            continue

        period = fin.get("period", "N/A")
        rev_cur = fin.get("매출액", {}).get("current") if isinstance(fin.get("매출액"), dict) else None
        rev_pre = fin.get("매출액", {}).get("previous") if isinstance(fin.get("매출액"), dict) else None
        op_cur = fin.get("영업이익", {}).get("current") if isinstance(fin.get("영업이익"), dict) else None
        op_pre = fin.get("영업이익", {}).get("previous") if isinstance(fin.get("영업이익"), dict) else None

        pct_str = _pct_change(rev_cur, rev_pre)
        pct_col = _pct_color(rev_cur, rev_pre)
        margin = _op_margin(rev_cur, op_cur)

        rows.append(
            f"<tr>"
            f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};font-weight:600;">{company}</td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};color:{MUTED};">{period}</td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};">{_fmt_억(rev_cur)}</td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};">{_fmt_억(op_cur)}</td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};">{margin}</td>'
            f'<td style="padding:10px 14px;border-bottom:1px solid {BORDER};color:{pct_col};font-weight:600;">{pct_str}</td>'
            f"</tr>"
        )

    rows_html = "\n".join(rows) if rows else (
        f'<tr><td colspan="6" style="padding:14px;text-align:center;color:{MUTED};">데이터 없음</td></tr>'
    )

    comment_block = ""
    if financial_comment:
        comment_block = f"""
<div style="background:#eef3fb;border-left:4px solid {PRIMARY_CONTAINER};
     border-radius:4px;padding:12px 16px;margin-top:14px;font-size:13px;color:{TEXT};">
  <strong>AI 종합 코멘트:</strong> {financial_comment}
</div>"""

    return f"""
<div style="margin-bottom:32px;">
  <h2 style="font-size:17px;font-weight:700;color:{PRIMARY};border-bottom:2px solid {PRIMARY};
       padding-bottom:6px;margin-bottom:16px;">1. 재무 현황 비교표</h2>
  <div style="overflow-x:auto;">
  <table style="width:100%;border-collapse:collapse;font-size:13px;background:{SURFACE};">
    <thead>
      <tr style="background:{PRIMARY};color:#fff;">
        <th style="padding:10px 14px;text-align:left;">거래처</th>
        <th style="padding:10px 14px;text-align:left;">기간</th>
        <th style="padding:10px 14px;text-align:right;">매출액 (당기)</th>
        <th style="padding:10px 14px;text-align:right;">영업이익 (당기)</th>
        <th style="padding:10px 14px;text-align:right;">영업이익률</th>
        <th style="padding:10px 14px;text-align:right;">전기대비 증감률</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  </div>
  {comment_block}
</div>"""


def _build_company_section(company: str, data: dict) -> str:
    news_list = data.get("news", {}).get(company, [])
    news_analysis = data.get("news_analysis", {}).get(company, {})
    disclosures = data.get("disclosures", {}).get(company, [])
    disclosure_analysis = data.get("disclosure_analysis", {}).get(company, {})
    insights = data.get("insights", {}).get(company, {})

    priority = insights.get("priority", "")
    priority_badge = _badge(f"우선순위: {priority}", _priority_color(priority)) if priority else ""

    # --- News block ---
    sentiment = news_analysis.get("sentiment", "")
    sentiment_badge = _badge(sentiment, _sentiment_color(sentiment)) if sentiment else ""
    news_summary = news_analysis.get("summary", "뉴스 요약 없음")
    top_issues = news_analysis.get("top_issues", [])
    importance = news_analysis.get("importance", "")

    news_body = f"""
<div style="margin-bottom:8px;">{sentiment_badge}
  {"&nbsp;<span style='font-size:12px;color:" + MUTED + ";'>중요도: " + str(importance) + "</span>" if importance else ""}
</div>
<p style="font-size:13px;color:{TEXT};margin:0 0 8px 0;line-height:1.6;">{news_summary}</p>
{"<div style='font-size:12px;font-weight:600;color:" + MUTED + ";margin-bottom:4px;'>주요 이슈</div>" + _bullet_list(top_issues) if top_issues else ""}
"""

    if news_list:
        news_links = "".join(
            f'<div style="font-size:12px;margin-top:4px;">'
            f'<a href="{item.get("link","#")}" style="color:{PRIMARY_CONTAINER};text-decoration:none;">'
            f'{item.get("title","(제목 없음)")}</a>'
            f'<span style="color:{MUTED};margin-left:6px;">{item.get("pubDate","")}</span>'
            f'</div>'
            for item in news_list[:5]
        )
        news_body += f'<div style="margin-top:10px;border-top:1px solid {BORDER};padding-top:8px;">' \
                     f'<div style="font-size:12px;font-weight:600;color:{MUTED};margin-bottom:4px;">관련 뉴스</div>' \
                     f'{news_links}</div>'

    # --- Disclosure block ---
    grade = disclosure_analysis.get("grade", "")
    grade_badge = _badge(f"등급: {grade}", _grade_color(grade)) if grade else ""
    disc_summary = disclosure_analysis.get("summary", "공시 요약 없음")
    disc_impact = disclosure_analysis.get("impact", "")
    special_notes = disclosure_analysis.get("special_notes", "")

    disc_body = f"""
<div style="margin-bottom:8px;">{grade_badge}</div>
<p style="font-size:13px;color:{TEXT};margin:0 0 6px 0;line-height:1.6;">{disc_summary}</p>
{"<p style='font-size:13px;color:" + TEXT + ";margin:0 0 6px 0;'><strong>영향도:</strong> " + disc_impact + "</p>" if disc_impact else ""}
{"<p style='font-size:13px;color:" + DANGER + ";margin:0;'><strong>특이사항:</strong> " + special_notes + "</p>" if special_notes else ""}
"""

    if disclosures:
        disc_links = "".join(
            f'<div style="font-size:12px;margin-top:4px;">'
            f'<a href="{item.get("url","#")}" style="color:{PRIMARY_CONTAINER};text-decoration:none;">'
            f'{item.get("report_nm","(공시명 없음)")}</a>'
            f'<span style="color:{MUTED};margin-left:6px;">{item.get("rcept_dt","")}</span>'
            f'</div>'
            for item in disclosures[:5]
        )
        disc_body += f'<div style="margin-top:10px;border-top:1px solid {BORDER};padding-top:8px;">' \
                     f'<div style="font-size:12px;font-weight:600;color:{MUTED};margin-bottom:4px;">공시 목록</div>' \
                     f'{disc_links}</div>'

    # --- Insights block ---
    order_forecast = insights.get("order_forecast", "")
    risks = insights.get("risks", [])
    opportunities = insights.get("opportunities", [])
    strategy = insights.get("strategy", "")

    insight_body = f"""
{"<p style='font-size:13px;color:" + TEXT + ";margin:0 0 10px 0;'><strong>수주 전망:</strong> " + order_forecast + "</p>" if order_forecast else ""}
<div style="display:table;width:100%;border-collapse:separate;border-spacing:8px;">
  <div style="display:table-row;">
    <div style="display:table-cell;width:50%;vertical-align:top;">
      <div style="font-size:12px;font-weight:600;color:{DANGER};margin-bottom:4px;">리스크</div>
      {_bullet_list(risks)}
    </div>
    <div style="display:table-cell;width:50%;vertical-align:top;">
      <div style="font-size:12px;font-weight:600;color:{SUCCESS};margin-bottom:4px;">기회요인</div>
      {_bullet_list(opportunities)}
    </div>
  </div>
</div>
{"<div style='margin-top:10px;padding:10px 14px;background:#f0faf3;border-radius:4px;font-size:13px;color:" + TEXT + ";'><strong>전략 제안:</strong> " + strategy + "</div>" if strategy else ""}
"""

    return f"""
<div style="background:{SURFACE};border:1px solid {BORDER};border-radius:8px;
     margin-bottom:24px;overflow:hidden;">
  <div style="background:{BACKGROUND};border-bottom:1px solid {BORDER};
       padding:14px 20px;display:flex;align-items:center;justify-content:space-between;">
    <h3 style="margin:0;font-size:16px;font-weight:700;color:{PRIMARY};">{company}</h3>
    <div>{priority_badge}</div>
  </div>
  <div style="padding:16px 20px;">
    {_card("뉴스 요약", news_body, PRIMARY_CONTAINER)}
    {_card("공시 분석", disc_body, SECONDARY)}
    {_card("영업 인사이트", insight_body, PRIMARY)}
  </div>
</div>"""


def _build_footer() -> str:
    return f"""
<div style="text-align:center;padding:24px;border-top:1px solid {BORDER};
     color:{MUTED};font-size:12px;margin-top:8px;">
  본 리포트는 AI 기반으로 자동 생성되었습니다.<br>
  <span style="font-size:11px;">PaperBox Insights &copy; {datetime.now().year}</span>
</div>"""


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def generate_report(data: dict, days: int = 7, save_dir: str = "reports") -> tuple[str, str]:
    """HTML 리포트를 생성하고 파일로 저장한다.

    Args:
        data: 뉴스, 공시, 재무, 분석 결과를 담은 딕셔너리.
        days: 분석 기간 (일수).
        save_dir: 저장 디렉토리 경로.

    Returns:
        (html_string, file_path) 튜플.
    """
    head = _build_head(days)
    fin_section = _build_financials_section(data)

    # Collect all companies from any available key
    all_companies: list[str] = []
    for key in ("news", "news_analysis", "disclosures", "disclosure_analysis", "insights", "financials"):
        if isinstance(data.get(key), dict):
            for c in data[key]:
                if c not in all_companies:
                    all_companies.append(c)

    company_sections = ""
    if all_companies:
        company_sections_html = "\n".join(_build_company_section(c, data) for c in all_companies)
        company_sections = f"""
<div style="margin-bottom:32px;">
  <h2 style="font-size:17px;font-weight:700;color:{PRIMARY};border-bottom:2px solid {PRIMARY};
       padding-bottom:6px;margin-bottom:16px;">2. 거래처별 분석</h2>
  {company_sections_html}
</div>"""

    footer = _build_footer()

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PaperBox Insights — 주간 거래처 분석 리포트</title>
</head>
<body style="margin:0;padding:0;background:{BACKGROUND};font-family:'Segoe UI',Arial,sans-serif;color:{TEXT};">
  <div style="max-width:900px;margin:24px auto;background:{SURFACE};
       border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.08);overflow:hidden;">
    {head}
    <div style="padding:28px 32px;">
      {fin_section}
      {company_sections}
    </div>
    {footer}
  </div>
</body>
</html>"""

    # Save to file
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    file_path = str(Path(save_dir) / filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)

    return html, file_path
