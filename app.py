"""
PaperBox Insights — 주간 거래처 분석 웹앱
종이용기 공급사(당사) 관점에서 오뚜기라면·삼양라면·농심·팔도를 매주 분석하고 리포트를 생성한다.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import os

from modules import news, dart, analyzer, report, mailer, config
from modules.news import COMPANIES
import scheduler

# ── 페이지 설정 ────────────────────────────────────────────────
st.set_page_config(
    page_title="PaperBox Insights",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 커스텀 CSS (Precision Analytical System 디자인) ─────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Hanken+Grotesk:wght@600;700;800&family=JetBrains+Mono:wght@500&display=swap');

:root {
  --primary: #002271;
  --primary-c: #203a89;
  --secondary: #006e1d;
  --bg: #f4f7f9;
  --border: #E5E5E5;
  --text: #212529;
  --muted: #666666;
  --success: #28A745;
  --danger: #DC3545;
  --warning: #FFC107;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

/* 사이드바 */
[data-testid="stSidebar"] {
  background: var(--primary) !important;
}
[data-testid="stSidebar"] * { color: rgba(255,255,255,0.85) !important; }
[data-testid="stSidebar"] .stRadio > label { font-family: 'Inter', sans-serif !important; font-size: 15px !important; }
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label p { font-size: 15px !important; font-weight: 500 !important; }
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label { padding: 6px 4px !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15) !important; }

/* 헤더 */
h1, h2, h3 { font-family: 'Hanken Grotesk', sans-serif !important; color: var(--primary) !important; }

/* 카드 */
.card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px 22px;
  margin-bottom: 16px;
}
.card-title {
  font-family: 'Hanken Grotesk', sans-serif;
  font-size: 15px;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 14px;
}

/* 뱃지 */
.badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 8px;
  font-size: 11.5px;
  font-weight: 600;
}
.badge-pos  { background: #d4edda; color: #155724; }
.badge-neg  { background: #f8d7da; color: #721c24; }
.badge-neu  { background: #e2e3e5; color: #383d41; }
.badge-high { background: #f8d7da; color: #721c24; }
.badge-mid  { background: #fff3cd; color: #856404; }
.badge-low  { background: #d4edda; color: #155724; }
.badge-A    { background: rgba(0,34,113,0.12); color: #002271; }
.badge-B    { background: rgba(0,110,29,0.12);  color: #006e1d; }
.badge-C    { background: #e2e3e5; color: #383d41; }
.badge-auto { background: rgba(0,34,113,0.1); color: var(--primary); }
.badge-manual{ background: rgba(0,110,29,0.1); color: var(--secondary); }
.badge-ok   { background: #d4edda; color: #155724; }
.badge-fail { background: #f8d7da; color: #721c24; }

/* 숫자 */
.mono { font-family: 'JetBrains Mono', monospace !important; font-size: 13px; }
.up   { color: var(--success); font-weight: 600; }
.down { color: var(--danger);  font-weight: 600; }

/* 섹션 구분선 */
.section-header {
  font-family: 'Hanken Grotesk', sans-serif;
  font-size: 13px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 6px 0 4px;
  border-bottom: 1px solid var(--border);
  margin: 16px 0 10px;
}

/* 인사이트 블록 */
.insight-block { background: #f8f9fb; border-left: 3px solid var(--primary-c); border-radius: 0 6px 6px 0; padding: 12px 14px; margin-bottom: 10px; }
.insight-risk  { border-left-color: var(--danger); }
.insight-opp   { border-left-color: var(--secondary); }
.insight-strat { border-left-color: var(--primary-c); }

/* 진행 단계 */
.step-row { display: flex; align-items: center; gap: 10px; padding: 7px 0; font-size: 13px; }
.step-done   { width:22px;height:22px;border-radius:50%;background:var(--success);color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0; }
.step-active { width:22px;height:22px;border-radius:50%;background:var(--primary-c);color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0; }
.step-pend   { width:22px;height:22px;border-radius:50%;background:var(--border);color:var(--muted);display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0; }
</style>
""", unsafe_allow_html=True)

# ── 스케줄러 초기화 (앱 시작 시 1회) ──────────────────────────
secrets = config.get_secrets()
scheduler.init_scheduler(
    hour=secrets.get("schedule_hour", 8),
    minute=secrets.get("schedule_minute", 0),
)

# ── 사이드바 ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:8px 4px 16px">
      <div style="font-family:'Hanken Grotesk',sans-serif;font-size:18px;font-weight:800;color:#fff">📦 PaperBox</div>
      <div style="font-size:12px;color:rgba(255,255,255,0.55);margin-top:2px">Supply Chain Portal</div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    page = st.radio(
        "메뉴",
        ["📊 리포트 생성", "📋 리포트 조회", "👥 수신자 관리", "⏱ 실행 이력", "⚙️ 설정"],
        label_visibility="collapsed",
    )

    st.divider()
    next_run = scheduler.get_next_run()
    st.markdown(f"""
    <div style="font-size:11px;color:rgba(255,255,255,0.5);padding:4px 0">
      🗓 다음 자동 실행<br>
      <span style="color:rgba(255,255,255,0.8);font-size:12px">{next_run}</span>
    </div>
    """, unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 1: 리포트 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if page == "📊 리포트 생성":
    st.markdown("## 📊 주간 거래처 분석 리포트 생성")
    st.caption(f"분석 대상: **오뚜기라면 · 삼양라면 · 농심 · 팔도**")

    col_ctrl, col_prev = st.columns([4, 6], gap="large")

    with col_ctrl:
        # 분석 설정
        st.markdown('<div class="card-title">분석 설정</div>', unsafe_allow_html=True)
        days = st.selectbox(
            "조회 기간",
            options=[7, 14, 30],
            format_func=lambda d: f"최근 {d}일 ({(datetime.now()-timedelta(days=d)).strftime('%m.%d')} ~ {datetime.now().strftime('%m.%d')})",
        )

        run_btn = st.button("▶ 리포트 생성 시작", type="primary", use_container_width=True)

        st.markdown("---")
        st.markdown('<div class="card-title">생성 진행도</div>', unsafe_allow_html=True)

        if "report_data" not in st.session_state:
            st.session_state.report_data = None
        if "gen_step" not in st.session_state:
            st.session_state.gen_step = 0

        # 진행 단계 표시
        STEPS = [
            "네이버 뉴스 수집 (4개사)",
            "DART 공시·재무 수집",
            "OpenAI 분석 및 요약",
            "통합 리포트 생성",
        ]

        progress_bar = st.progress(st.session_state.gen_step / len(STEPS))
        step_placeholders = [st.empty() for _ in STEPS]

        def render_steps(current_step: int) -> None:
            for i, s in enumerate(STEPS):
                if i < current_step:
                    icon, style = "✅", "color:#155724"
                elif i == current_step:
                    icon, style = "⟳", "color:#002271;font-weight:600"
                else:
                    icon, style = "○", "color:#aaa"
                step_placeholders[i].markdown(
                    f'<div class="step-row"><span>{icon}</span><span style="{style}">{s}</span></div>',
                    unsafe_allow_html=True,
                )

        render_steps(st.session_state.gen_step)

    # 리포트 생성 실행
    if run_btn:
        secrets = config.get_secrets()
        data = {}

        with col_ctrl:
            # Step 1: 뉴스
            st.session_state.gen_step = 0
            render_steps(0)
            progress_bar.progress(0.1)
            with st.spinner("뉴스 수집 중..."):
                data["news"] = news.fetch_all_news(
                    COMPANIES,
                    secrets.get("naver_client_id", ""),
                    secrets.get("naver_client_secret", ""),
                    days=days,
                )
            st.session_state.gen_step = 1
            render_steps(1)

            # Step 2: DART
            progress_bar.progress(0.35)
            with st.spinner("DART 공시 수집 중..."):
                data["disclosures"] = dart.fetch_all_disclosures(
                    COMPANIES, secrets.get("dart_api_key", ""), days=days
                )
                data["financials"] = dart.fetch_all_financials(
                    COMPANIES, secrets.get("dart_api_key", "")
                )
            st.session_state.gen_step = 2
            render_steps(2)

            # Step 3: AI 분석
            progress_bar.progress(0.6)
            oai_key = secrets.get("openai_api_key", "")
            data["news_analysis"] = {}
            data["disclosure_analysis"] = {}
            data["insights"] = {}

            with st.spinner("OpenAI 분석 중..."):
                for c in COMPANIES:
                    name = c["name"]
                    data["news_analysis"][name] = analyzer.analyze_news(
                        name, data["news"].get(name, []), oai_key
                    )
                    data["disclosure_analysis"][name] = analyzer.analyze_disclosures(
                        name, data["disclosures"].get(name, []), oai_key
                    )
                    data["insights"][name] = analyzer.generate_insight(
                        name,
                        data["news_analysis"][name],
                        data["disclosure_analysis"][name],
                        data["financials"].get(name),
                        oai_key,
                    )
                data["financial_comment"] = analyzer.analyze_financials(
                    data["financials"], oai_key
                )
            st.session_state.gen_step = 3
            render_steps(3)

            # Step 4: 리포트 생성
            progress_bar.progress(0.9)
            with st.spinner("리포트 생성 중..."):
                html_str, file_path = report.generate_report(data, days=days)
                st.session_state.report_data = data
                st.session_state.report_html = html_str
                st.session_state.report_path = file_path
            st.session_state.gen_step = 4
            render_steps(4)

            progress_bar.progress(1.0)
            st.success(f"✅ 리포트 생성 완료 — {file_path}")
            config.append_log({
                "timestamp": datetime.now().isoformat(),
                "type": "manual",
                "status": "success",
                "report_path": file_path,
                "mail_sent": 0,
                "mail_failed": 0,
            })

    # 리포트 미리보기 영역
    with col_prev:
        st.markdown('<div class="card-title">리포트 미리보기</div>', unsafe_allow_html=True)

        if st.session_state.report_data:
            data = st.session_state.report_data
            tab_fin, tab_news, tab_disc, tab_ins = st.tabs(
                ["📈 재무분석", "📰 뉴스", "📋 공시", "💡 인사이트"]
            )

            # ── 재무분석 탭 ──
            with tab_fin:
                fin_rows = []
                for c in COMPANIES:
                    fd = data["financials"].get(c["name"])
                    if fd:
                        rev_c = fd.get("매출액", {}).get("current") or 0
                        rev_p = fd.get("매출액", {}).get("previous") or 0
                        op_c  = fd.get("영업이익", {}).get("current") or 0
                        op_p  = fd.get("영업이익", {}).get("previous") or 0
                        rev_chg = ((rev_c - rev_p) / abs(rev_p) * 100) if rev_p else 0
                        op_margin = (op_c / rev_c * 100) if rev_c else 0
                        fin_rows.append({
                            "거래처": c["name"],
                            "기간": fd.get("period", "-"),
                            "매출액(억원)": f"{rev_c/1e8:.1f}",
                            "영업이익(억원)": f"{op_c/1e8:.1f}",
                            "영업이익률(%)": f"{op_margin:.1f}",
                            "매출 증감률(%)": f"{rev_chg:+.1f}",
                        })

                if fin_rows:
                    df = pd.DataFrame(fin_rows)
                    st.dataframe(df, use_container_width=True, hide_index=True)

                    # 막대 차트
                    companies = [r["거래처"] for r in fin_rows]
                    rev_vals  = [float(r["매출액(억원)"]) for r in fin_rows]
                    op_vals   = [float(r["영업이익(억원)"]) for r in fin_rows]

                    fig = go.Figure(data=[
                        go.Bar(name="매출액(억원)", x=companies, y=rev_vals,
                               marker_color="#002271", opacity=0.85),
                        go.Bar(name="영업이익(억원)", x=companies, y=op_vals,
                               marker_color="#006e1d", opacity=0.85),
                    ])
                    fig.update_layout(
                        barmode="group", height=300,
                        margin=dict(l=0, r=0, t=30, b=0),
                        plot_bgcolor="#fff", paper_bgcolor="#fff",
                        legend=dict(orientation="h", y=-0.2),
                        font=dict(family="Inter"),
                    )
                    fig.update_xaxes(showgrid=False)
                    fig.update_yaxes(gridcolor="#f0f0f0")
                    st.plotly_chart(fig, use_container_width=True)

                if data.get("financial_comment"):
                    st.info(f"💬 AI 종합 코멘트: {data['financial_comment']}")
                else:
                    st.info("재무 데이터가 없습니다.")

            # ── 뉴스 탭 ──
            with tab_news:
                for c in COMPANIES:
                    name = c["name"]
                    ana = data["news_analysis"].get(name, {})
                    items = data["news"].get(name, [])
                    sentiment = ana.get("sentiment", "중립")
                    badge_cls = {"긍정": "badge-pos", "부정": "badge-neg"}.get(sentiment, "badge-neu")
                    imp = ana.get("importance", "보통")
                    imp_cls = {"높음": "badge-high", "보통": "badge-mid", "낮음": "badge-low"}.get(imp, "badge-mid")

                    with st.expander(f"**{name}** — 뉴스 {len(items)}건", expanded=(name == COMPANIES[0]["name"])):
                        st.markdown(
                            f'<span class="badge {badge_cls}">{sentiment}</span> '
                            f'<span class="badge {imp_cls}">중요도: {imp}</span>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**요약**: {ana.get('summary','–')}")
                        st.markdown(f"**영향 분석**: {ana.get('impact','–')}")
                        issues = ana.get("top_issues", [])
                        if issues:
                            st.markdown("**주요 이슈 Top 3**")
                            for issue in issues[:3]:
                                st.markdown(f"• {issue}")
                        if items:
                            st.markdown("**뉴스 목록**")
                            for item in items[:5]:
                                st.markdown(f"- [{item.get('title','–')}]({item.get('link','#')}) `{item.get('pubDate','')[:10]}`")

            # ── 공시 탭 ──
            with tab_disc:
                all_disc = []
                for c in COMPANIES:
                    for d in data["disclosures"].get(c["name"], []):
                        d["company"] = c["name"]
                        all_disc.append(d)

                if all_disc:
                    for c in COMPANIES:
                        name = c["name"]
                        items = data["disclosures"].get(name, [])
                        ana = data["disclosure_analysis"].get(name, {})
                        if not items:
                            continue
                        grade = ana.get("grade", "중")
                        g_cls = {"상": "badge-high", "중": "badge-mid", "하": "badge-low"}.get(grade, "badge-mid")
                        with st.expander(f"**{name}** — 공시 {len(items)}건", expanded=False):
                            st.markdown(
                                f'<span class="badge {g_cls}">중요도: {grade}</span>',
                                unsafe_allow_html=True,
                            )
                            st.markdown(f"**요약**: {ana.get('summary','–')}")
                            st.markdown(f"**영향**: {ana.get('impact','–')}")
                            for item in items[:5]:
                                st.markdown(f"- [{item.get('report_nm','–')}]({item.get('url','#')}) `{item.get('rcept_dt','')}`")
                else:
                    st.info("해당 기간 공시 자료가 없습니다.")

            # ── 인사이트 탭 ──
            with tab_ins:
                for c in COMPANIES:
                    name = c["name"]
                    ins = data["insights"].get(name, {})
                    priority = ins.get("priority", "B")
                    p_cls = {"A": "badge-A", "B": "badge-B", "C": "badge-C"}.get(priority, "badge-B")
                    with st.expander(f"**{name}**", expanded=True):
                        st.markdown(
                            f'<span class="badge {p_cls}">영업 우선순위: {priority}등급</span>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**발주 전망**: {ins.get('order_forecast','–')}")
                        col_r, col_o = st.columns(2)
                        with col_r:
                            st.markdown("**⚠ 리스크**")
                            for r in ins.get("risks", []):
                                st.markdown(f"• {r}")
                        with col_o:
                            st.markdown("**✅ 기회**")
                            for o in ins.get("opportunities", []):
                                st.markdown(f"• {o}")
                        st.markdown(f"**대응 전략**: {ins.get('strategy','–')}")

            st.divider()
            # 메일 발송
            col_m1, col_m2 = st.columns([3, 1])
            with col_m1:
                recipients = config.load_recipients()
                active = [r for r in recipients if r.get("active")]
                st.caption(f"활성 수신자 {len(active)}명에게 발송합니다.")
            with col_m2:
                if st.button("✉ 메일 발송", type="secondary", use_container_width=True):
                    if not active:
                        st.warning("활성화된 수신자가 없습니다.")
                    else:
                        secrets = config.get_secrets()
                        smtp_cfg = {
                            "host": secrets.get("smtp_host"),
                            "port": secrets.get("smtp_port", 587),
                            "user": secrets.get("smtp_user"),
                            "password": secrets.get("smtp_password"),
                            "from": secrets.get("smtp_from"),
                        }
                        result = mailer.send_report(
                            st.session_state.report_html,
                            active, smtp_cfg,
                            attachment_path=st.session_state.get("report_path"),
                        )
                        st.success(f"발송 성공: {len(result['success'])}명")
                        if result["failed"]:
                            st.error(f"발송 실패: {len(result['failed'])}명")
                        config.append_log({
                            "timestamp": datetime.now().isoformat(),
                            "type": "manual_mail",
                            "status": "success",
                            "report_path": st.session_state.get("report_path", ""),
                            "mail_sent": len(result["success"]),
                            "mail_failed": len(result["failed"]),
                        })
        else:
            st.markdown("""
            <div style="text-align:center;padding:60px 20px;color:#aaa">
              <div style="font-size:48px">📊</div>
              <div style="margin-top:12px;font-size:15px">왼쪽에서 기간을 선택하고<br>리포트 생성 시작 버튼을 눌러주세요</div>
            </div>
            """, unsafe_allow_html=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 2: 리포트 조회
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif page == "📋 리포트 조회":
    st.markdown("## 📋 리포트 조회")

    reports_list = config.list_reports()
    if not reports_list:
        st.info("저장된 리포트가 없습니다. 먼저 리포트를 생성해주세요.")
    else:
        options = {r["filename"]: r["path"] for r in reports_list}
        selected = st.selectbox(
            "리포트 선택",
            list(options.keys()),
            format_func=lambda f: f.replace("report_", "").replace(".html", "").replace("_", " "),
        )
        col_dl, _ = st.columns([2, 8])
        with col_dl:
            with open(options[selected], "r", encoding="utf-8") as f:
                html_content = f.read()
            st.download_button(
                "⬇ 다운로드",
                data=html_content,
                file_name=selected,
                mime="text/html",
            )
        st.components.v1.html(html_content, height=800, scrolling=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 3: 수신자 관리
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif page == "👥 수신자 관리":
    st.markdown("## 👥 메일 수신자 관리")

    # 추가 폼
    with st.form("add_recipient_form", clear_on_submit=True):
        st.markdown("#### 수신자 추가")
        c1, c2, c3, c4 = st.columns([2, 3, 2, 1])
        with c1:
            new_name = st.text_input("이름", placeholder="홍길동")
        with c2:
            new_email = st.text_input("이메일", placeholder="hong@company.com")
        with c3:
            new_dept = st.text_input("부서", placeholder="영업팀")
        with c4:
            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("➕ 추가", use_container_width=True)

        if submitted:
            if not new_name or not new_email:
                st.error("이름과 이메일은 필수입니다.")
            elif "@" not in new_email:
                st.error("유효한 이메일 주소를 입력하세요.")
            else:
                config.add_recipient(new_name, new_email, new_dept)
                st.success(f"✅ {new_name} ({new_email}) 추가 완료")
                st.rerun()

    st.divider()

    # 수신자 목록
    recipients = config.load_recipients()
    if not recipients:
        st.info("등록된 수신자가 없습니다.")
    else:
        st.markdown(f"#### 수신자 목록 ({len(recipients)}명 / 활성: {sum(1 for r in recipients if r.get('active'))}명)")
        header = st.columns([2, 3, 2, 1, 1])
        for h, t in zip(header, ["이름", "이메일", "부서", "활성화", "삭제"]):
            h.markdown(f"**{t}**")
        st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)

        for idx, r in enumerate(recipients):
            col1, col2, col3, col4, col5 = st.columns([2, 3, 2, 1, 1])
            col1.write(r.get("name", ""))
            col2.write(r.get("email", ""))
            col3.write(r.get("dept", ""))
            is_active = r.get("active", True)
            badge = '<span class="badge badge-ok">활성</span>' if is_active else '<span class="badge badge-neu">비활성</span>'
            col4.markdown(badge, unsafe_allow_html=True)
            if col5.button("🗑", key=f"del_{idx}_{r['email']}", help=f"{r['email']} 삭제"):
                config.delete_recipient(r["email"])
                st.rerun()
            if col4.button("전환", key=f"tog_{idx}_{r['email']}", help="활성/비활성 전환"):
                config.toggle_recipient(r["email"])
                st.rerun()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 4: 실행 이력
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif page == "⏱ 실행 이력":
    st.markdown("## ⏱ 실행 이력")

    logs = config.load_logs()
    if not logs:
        st.info("실행 이력이 없습니다.")
    else:
        rows = []
        for log in logs:
            ts = log.get("timestamp", "")[:16].replace("T", " ")
            run_type = log.get("type", "-")
            type_badge = "자동" if run_type == "auto" else "수동"
            type_cls = "badge-auto" if run_type == "auto" else "badge-manual"
            status = log.get("status", "-")
            status_cls = "badge-ok" if status == "success" else "badge-fail"
            status_label = "성공" if status == "success" else "실패"
            rows.append({
                "실행일시": ts,
                "실행유형": f'<span class="badge {type_cls}">{type_badge}</span>',
                "상태": f'<span class="badge {status_cls}">{status_label}</span>',
                "메일 발송": f'{log.get("mail_sent", 0)}명',
                "리포트": log.get("report_path", "-").split("/")[-1] or "-",
            })

        df = pd.DataFrame(rows)
        st.write(
            df.to_html(escape=False, index=False, classes="dataframe"),
            unsafe_allow_html=True,
        )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 5: 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
elif page == "⚙️ 설정":
    st.markdown("## ⚙️ 시스템 설정")
    st.info("💡 API 키는 Streamlit Community Cloud의 Secrets 설정에서 관리합니다. 아래는 현재 연결 상태를 확인하는 테스트 기능입니다.")

    secrets = config.get_secrets()

    # ── Naver API ──
    with st.expander("📡 네이버 뉴스 API", expanded=True):
        c1, c2 = st.columns(2)
        c1.text_input("Client ID", value=secrets.get("naver_client_id", "")[:4] + "****" if secrets.get("naver_client_id") else "", disabled=True, key="cfg_naver_id")
        c2.text_input("Client Secret", value="****" if secrets.get("naver_client_secret") else "미설정", disabled=True, key="cfg_naver_secret")
        if st.button("🔌 네이버 API 연결 테스트", key="btn_test_naver"):
            cid = secrets.get("naver_client_id", "")
            csec = secrets.get("naver_client_secret", "")
            if not cid or not csec:
                st.error("❌ Client ID / Secret 미설정")
            else:
                import requests as _req
                try:
                    r = _req.get(
                        "https://openapi.naver.com/v1/search/news.json",
                        headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
                        params={"query": "테스트", "display": 1},
                        timeout=5,
                    )
                    if r.status_code == 200:
                        st.success("✅ 네이버 API 연결 성공")
                    else:
                        st.error(f"❌ 응답 오류: {r.status_code}")
                except Exception as e:
                    st.error(f"❌ 연결 실패: {e}")

    # ── DART API ──
    with st.expander("📂 DART Open API"):
        st.text_input("API Key", value="****" if secrets.get("dart_api_key") else "미설정", disabled=True, key="cfg_dart_key")
        if st.button("🔌 DART API 연결 테스트", key="btn_test_dart"):
            key = secrets.get("dart_api_key", "")
            if not key:
                st.error("❌ API Key 미설정")
            else:
                import requests as _req
                try:
                    r = _req.get(
                        "https://opendart.fss.or.kr/api/list.json",
                        params={"crtfc_key": key, "corp_code": "00155653", "page_count": 1},
                        timeout=5,
                    )
                    res = r.json()
                    if res.get("status") in ("000", "013"):
                        st.success("✅ DART API 연결 성공")
                    else:
                        st.error(f"❌ 응답 코드: {res.get('status')} — {res.get('message','')}")
                except Exception as e:
                    st.error(f"❌ 연결 실패: {e}")

    # ── OpenAI ──
    with st.expander("🤖 OpenAI API"):
        st.text_input("API Key", value="sk-****" if secrets.get("openai_api_key") else "미설정", disabled=True, key="cfg_oai_key")
        st.text_input("모델", value="gpt-4o-mini", disabled=True, key="cfg_oai_model")
        if st.button("🔌 OpenAI API 연결 테스트", key="btn_test_oai"):
            key = secrets.get("openai_api_key", "")
            if not key:
                st.error("❌ API Key 미설정")
            else:
                try:
                    from openai import OpenAI as _OAI
                    client = _OAI(api_key=key)
                    resp = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=5,
                    )
                    st.success("✅ OpenAI API 연결 성공")
                except Exception as e:
                    st.error(f"❌ 연결 실패: {e}")

    # ── SMTP ──
    with st.expander("📧 SMTP 메일 설정"):
        c1, c2 = st.columns([3, 1])
        c1.text_input("서버 주소", value=secrets.get("smtp_host", "미설정"), disabled=True, key="cfg_smtp_host")
        c2.text_input("포트", value=str(secrets.get("smtp_port", 587)), disabled=True, key="cfg_smtp_port")
        st.text_input("계정", value=secrets.get("smtp_user", "미설정"), disabled=True, key="cfg_smtp_user")
        st.text_input("비밀번호", value="****" if secrets.get("smtp_password") else "미설정", type="password", disabled=True, key="cfg_smtp_pw")
        st.text_input("발신자 이메일", value=secrets.get("smtp_from", "미설정"), disabled=True, key="cfg_smtp_from")
        if st.button("🔌 SMTP 연결 테스트", key="btn_test_smtp"):
            smtp_cfg = {
                "host": secrets.get("smtp_host"),
                "port": secrets.get("smtp_port", 587),
                "user": secrets.get("smtp_user"),
                "password": secrets.get("smtp_password"),
                "from": secrets.get("smtp_from"),
            }
            ok, msg = mailer.test_smtp_connection(smtp_cfg)
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")

    # ── 스케줄 설정 ──
    with st.expander("🗓 자동 실행 스케줄"):
        sh = secrets.get("schedule_hour", 8)
        sm = secrets.get("schedule_minute", 0)
        st.markdown(f"**현재 스케줄**: 매주 월요일 `{sh:02d}:{sm:02d}` 자동 실행")
        st.markdown(f"**다음 실행**: {scheduler.get_next_run()}")
        st.caption("스케줄 시각 변경은 Streamlit Secrets의 SCHEDULE_HOUR / SCHEDULE_MINUTE를 수정 후 앱을 재시작하세요.")
