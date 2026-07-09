"""설정값 로드, 저장, 검증을 담당한다."""
import json
import os
from pathlib import Path
import streamlit as st

RECIPIENTS_FILE = "recipients.json"
LOG_FILE = "logs/execution.log"


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

def load_recipients() -> list[dict]:
    """recipients.json을 읽어 수신자 목록을 반환한다. 파일이 없으면 빈 리스트 반환."""
    try:
        with open(RECIPIENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_recipients(recipients: list[dict]) -> None:
    """수신자 목록을 recipients.json에 저장한다."""
    with open(RECIPIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(recipients, f, ensure_ascii=False, indent=2)


def add_recipient(name: str, email: str, dept: str) -> list[dict]:
    """수신자를 추가하고 업데이트된 목록을 반환한다."""
    recipients = load_recipients()
    recipients.append({
        "name": name,
        "email": email,
        "dept": dept,
        "active": True,
    })
    save_recipients(recipients)
    return recipients


def delete_recipient(email: str) -> list[dict]:
    """이메일이 일치하는 수신자를 삭제하고 업데이트된 목록을 반환한다."""
    recipients = load_recipients()
    recipients = [r for r in recipients if r.get("email") != email]
    save_recipients(recipients)
    return recipients


def toggle_recipient(email: str) -> list[dict]:
    """이메일이 일치하는 수신자의 active 상태를 반전시키고 업데이트된 목록을 반환한다."""
    recipients = load_recipients()
    for r in recipients:
        if r.get("email") == email:
            r["active"] = not r.get("active", True)
            break
    save_recipients(recipients)
    return recipients


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def append_log(entry: dict) -> None:
    """실행 로그를 logs/execution.log에 JSON 라인 형식으로 추가한다."""
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_logs() -> list[dict]:
    """logs/execution.log를 읽어 최신순으로 정렬된 최대 100개의 로그 항목을 반환한다."""
    log_path = Path(LOG_FILE)
    if not log_path.exists():
        return []

    entries: list[dict] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    # Most recent first, max 100
    return list(reversed(entries))[-100:] if len(entries) > 100 else list(reversed(entries))


# ---------------------------------------------------------------------------
# Secrets / environment
# ---------------------------------------------------------------------------

def get_secrets() -> dict:
    """Streamlit Secrets 또는 환경 변수에서 설정값을 읽어 딕셔너리로 반환한다.

    누락된 키는 빈 문자열 또는 기본값으로 채워진다.
    """

    def _get(key: str, default: str = "") -> str:
        # Try st.secrets — check both original case and uppercase
        try:
            for k in (key, key.upper()):
                val = st.secrets.get(k)
                if val is not None:
                    return str(val)
        except Exception:
            pass
        # Fall back to environment variables (both cases)
        for k in (key, key.upper()):
            val = os.environ.get(k)
            if val is not None:
                return val
        return default

    def _get_int(key: str, default: int) -> int:
        raw = _get(key, str(default))
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    return {
        "naver_client_id": _get("NAVER_CLIENT_ID"),
        "naver_client_secret": _get("NAVER_CLIENT_SECRET"),
        "dart_api_key": _get("DART_API_KEY"),
        "openai_api_key": _get("OPENAI_API_KEY"),
        "smtp_host": _get("SMTP_HOST"),
        "smtp_port": _get_int("SMTP_PORT", 587),
        "smtp_user": _get("SMTP_USER"),
        "smtp_password": _get("SMTP_PASSWORD"),
        "smtp_from": _get("SMTP_FROM"),
        "schedule_hour": _get_int("SCHEDULE_HOUR", 8),
        "schedule_minute": _get_int("SCHEDULE_MINUTE", 0),
    }


# ---------------------------------------------------------------------------
# Report listing
# ---------------------------------------------------------------------------

def list_reports(reports_dir: str = "reports") -> list[dict]:
    """지정된 디렉토리의 HTML 리포트 파일 목록을 최신순으로 반환한다.

    Returns:
        [{"filename": .., "path": .., "created_at": ..}, ...] (최신 파일 먼저)
    """
    dir_path = Path(reports_dir)
    if not dir_path.exists():
        return []

    files: list[dict] = []
    for html_file in dir_path.glob("*.html"):
        try:
            stat = html_file.stat()
            created_at = stat.st_mtime
        except OSError:
            created_at = 0.0

        files.append({
            "filename": html_file.name,
            "path": str(html_file),
            "created_at": created_at,
        })

    files.sort(key=lambda x: x["created_at"], reverse=True)
    return files
