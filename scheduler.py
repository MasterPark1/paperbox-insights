"""
APScheduler를 사용해 매주 월요일 지정 시각에 자동으로 리포트를 생성하고 메일 발송한다.
Streamlit 앱 시작 시 한 번만 초기화된다.
"""
import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from datetime import datetime

from modules import news, dart, analyzer, report, mailer, config

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_weekly_job() -> None:
    """매주 월요일 자동 실행되는 리포트 생성 및 메일 발송 작업."""
    started_at = datetime.now().isoformat()
    log_entry: dict = {
        "started_at": started_at,
        "status": "unknown",
        "error": None,
    }

    try:
        secrets = config.get_secrets()

        # ------------------------------------------------------------------ #
        # 1. 데이터 수집
        # ------------------------------------------------------------------ #
        all_news: dict = news.fetch_all_news(
            client_id=secrets.get("naver_client_id", ""),
            client_secret=secrets.get("naver_client_secret", ""),
        )

        all_disclosures: dict = dart.fetch_all_disclosures(
            api_key=secrets.get("dart_api_key", ""),
        )

        all_financials: dict = dart.fetch_all_financials(
            api_key=secrets.get("dart_api_key", ""),
        )

        # ------------------------------------------------------------------ #
        # 2. AI 분석
        # ------------------------------------------------------------------ #
        news_analysis: dict = {}
        disclosure_analysis: dict = {}
        insights: dict = {}

        companies: list[str] = list(
            set(list(all_news.keys()) + list(all_disclosures.keys()) + list(all_financials.keys()))
        )

        for company in companies:
            company_news = all_news.get(company, [])
            company_disclosures = all_disclosures.get(company, [])
            company_financials = all_financials.get(company)

            news_analysis[company] = analyzer.analyze_news(
                company=company,
                news_items=company_news,
                api_key=secrets.get("openai_api_key", ""),
            )

            disclosure_analysis[company] = analyzer.analyze_disclosures(
                company=company,
                disclosures=company_disclosures,
                api_key=secrets.get("openai_api_key", ""),
            )

            insights[company] = analyzer.generate_insights(
                company=company,
                news_analysis=news_analysis[company],
                disclosure_analysis=disclosure_analysis[company],
                financials=company_financials,
                api_key=secrets.get("openai_api_key", ""),
            )

        financial_comment: str = analyzer.generate_financial_comment(
            financials=all_financials,
            api_key=secrets.get("openai_api_key", ""),
        )

        # ------------------------------------------------------------------ #
        # 3. 리포트 생성
        # ------------------------------------------------------------------ #
        data: dict = {
            "news": all_news,
            "news_analysis": news_analysis,
            "disclosures": all_disclosures,
            "disclosure_analysis": disclosure_analysis,
            "financials": all_financials,
            "financial_comment": financial_comment,
            "insights": insights,
        }

        html_body, file_path = report.generate_report(data=data, days=7)

        # ------------------------------------------------------------------ #
        # 4. 메일 발송
        # ------------------------------------------------------------------ #
        recipients = config.load_recipients()

        smtp_config: dict = {
            "host": secrets.get("smtp_host", ""),
            "port": secrets.get("smtp_port", 587),
            "user": secrets.get("smtp_user", ""),
            "password": secrets.get("smtp_password", ""),
            "from": secrets.get("smtp_from", ""),
        }

        mail_result = mailer.send_report(
            html_body=html_body,
            recipients=recipients,
            smtp_config=smtp_config,
            attachment_path=file_path,
        )

        log_entry.update({
            "status": "success",
            "companies": companies,
            "report_file": file_path,
            "mail_success": mail_result.get("success", []),
            "mail_failed": mail_result.get("failed", []),
            "finished_at": datetime.now().isoformat(),
        })
        logger.info(
            "주간 리포트 작업 완료 — 발송 성공: %d, 실패: %d",
            len(mail_result.get("success", [])),
            len(mail_result.get("failed", [])),
        )

    except Exception as exc:
        log_entry.update({
            "status": "error",
            "error": str(exc),
            "finished_at": datetime.now().isoformat(),
        })
        logger.error("주간 리포트 작업 오류: %s", exc, exc_info=True)

    finally:
        config.append_log(log_entry)


def init_scheduler(hour: int = 8, minute: int = 0) -> None:
    """백그라운드 스케줄러를 초기화하고 주간 작업을 등록한다.

    Streamlit 세션 상태를 사용해 앱 수명 동안 단 한 번만 초기화된다.

    Args:
        hour: 실행 시각 (시). 기본 8.
        minute: 실행 시각 (분). 기본 0.
    """
    global _scheduler

    if st.session_state.get("scheduler_started"):
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    _scheduler.add_job(
        func=run_weekly_job,
        trigger=CronTrigger(day_of_week="mon", hour=hour, minute=minute),
        id="weekly_report",
        name="주간 거래처 분석 리포트",
        replace_existing=True,
    )
    _scheduler.start()

    st.session_state["scheduler_started"] = True
    logger.info("스케줄러 시작: 매주 월요일 %02d:%02d", hour, minute)


def get_next_run() -> str:
    """다음 스케줄 실행 시각을 문자열로 반환한다.

    Returns:
        포맷된 다음 실행 시각 또는 "스케줄러 미실행".
    """
    global _scheduler

    if _scheduler is None or not st.session_state.get("scheduler_started"):
        return "스케줄러 미실행"

    try:
        job = _scheduler.get_job("weekly_report")
        if job is None:
            return "스케줄러 미실행"
        next_run = job.next_run_time
        if next_run is None:
            return "스케줄러 미실행"
        return next_run.strftime("%Y-%m-%d %H:%M:%S (%Z)")
    except Exception as exc:
        logger.warning("다음 실행 시각 조회 실패: %s", exc)
        return "스케줄러 미실행"
