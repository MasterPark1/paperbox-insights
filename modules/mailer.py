"""회사 SMTP 서버를 통해 HTML 리포트를 메일로 발송한다."""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import os
import json
import logging

logger = logging.getLogger(__name__)


def send_report(
    html_body: str,
    recipients: list[dict],
    smtp_config: dict,
    subject: str = None,
    attachment_path: str = None,
) -> dict:
    """HTML 리포트를 활성화된 수신자들에게 개별 발송한다.

    Args:
        html_body: 발송할 HTML 본문 문자열.
        recipients: 수신자 목록. 각 항목은 {"name": .., "email": .., "active": ..} 형태.
        smtp_config: SMTP 연결 정보 딕셔너리.
                     {"host": .., "port": 587, "user": .., "password": .., "from": ..}
        subject: 메일 제목. None이면 기본값 사용.
        attachment_path: 첨부 파일 경로. None이거나 파일이 없으면 무시.

    Returns:
        {"success": [emails], "failed": [{"email":.., "error":..}]}
    """
    if subject is None:
        subject = (
            f"[PaperBox Insights] 주간 거래처 분석 리포트 "
            f"{datetime.now().strftime('%Y-%m-%d')}"
        )

    host = smtp_config.get("host", "")
    port = int(smtp_config.get("port", 587))
    user = smtp_config.get("user", "")
    password = smtp_config.get("password", "")
    from_addr = smtp_config.get("from", user)

    active_recipients = [r for r in recipients if r.get("active", False)]

    result: dict = {"success": [], "failed": []}

    if not active_recipients:
        logger.info("활성 수신자가 없어 메일 발송을 건너뜁니다.")
        return result

    # Read attachment once if provided
    attachment_data: bytes | None = None
    attachment_filename: str | None = None
    if attachment_path and os.path.isfile(attachment_path):
        with open(attachment_path, "rb") as fh:
            attachment_data = fh.read()
        attachment_filename = os.path.basename(attachment_path)

    for recipient in active_recipients:
        to_email: str = recipient.get("email", "")
        to_name: str = recipient.get("name", "")
        if not to_email:
            logger.warning("이메일 주소가 없는 수신자를 건너뜁니다: %s", recipient)
            continue

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"PaperBox Insights <{from_addr}>"
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if attachment_data is not None and attachment_filename is not None:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment_data)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment_filename}"',
            )
            msg.attach(part)

        try:
            if port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, context=context) as server:
                    server.login(user, password)
                    server.sendmail(from_addr, [to_email], msg.as_string())
            else:
                with smtplib.SMTP(host, port) as server:
                    server.ehlo()
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                    server.login(user, password)
                    server.sendmail(from_addr, [to_email], msg.as_string())

            logger.info("메일 발송 성공: %s", to_email)
            result["success"].append(to_email)

        except Exception as exc:
            error_msg = str(exc)
            logger.error("메일 발송 실패 (%s): %s", to_email, error_msg)
            result["failed"].append({"email": to_email, "error": error_msg})

    return result


def test_smtp_connection(smtp_config: dict) -> tuple[bool, str]:
    """SMTP 서버 연결 및 로그인을 테스트한다.

    Args:
        smtp_config: SMTP 연결 정보 딕셔너리.

    Returns:
        (True, "연결 성공") 또는 (False, 오류_메시지) 튜플.
    """
    host = smtp_config.get("host", "")
    port = int(smtp_config.get("port", 587))
    user = smtp_config.get("user", "")
    password = smtp_config.get("password", "")

    try:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                server.login(user, password)
        else:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(user, password)

        logger.info("SMTP 연결 테스트 성공: %s:%s", host, port)
        return True, "연결 성공"

    except smtplib.SMTPAuthenticationError as exc:
        msg = f"인증 실패: {exc}"
        logger.error("SMTP 연결 테스트 실패: %s", msg)
        return False, msg

    except smtplib.SMTPConnectError as exc:
        msg = f"서버 연결 오류: {exc}"
        logger.error("SMTP 연결 테스트 실패: %s", msg)
        return False, msg

    except Exception as exc:
        msg = str(exc)
        logger.error("SMTP 연결 테스트 실패: %s", msg)
        return False, msg
