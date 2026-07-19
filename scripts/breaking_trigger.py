"""속보 트리거 — 대형 이슈 감지 시 정규 크론 밖 즉시 발행 디스패치 (2026-07-19 신설).

배경(사용자 지시): KIMI K3·쿠팡 물류센터 화재급 실시간 급상승 이슈는 트래픽이 몰리는데,
정규 크론(테크 4회/주식 16:30)은 슬롯을 기다려 놓친다. 2시간 간격으로 구글뉴스 한국판
톱스토리를 스캔해 '다수 매체가 다루는 대형 이슈'를 Gemini로 판정하고, 해당 트랙의
발행 워크플로를 workflow_dispatch로 즉시 트리거한다.

라우팅: tech(IT·테크·가전·AI) → tech_post.yml(breaking) / finance(시장·금융 대형) → stock_post.yml
중복 방지: data/breaking_history.json (이슈 지문 7일 + 하루 최대 2회 디스패치 상한)
"""
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KST = timezone(timedelta(hours=9))
HIST_PATH = os.path.join(ROOT, "data", "breaking_history.json")
RSS_URL = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
DAILY_CAP = 2          # 하루 최대 디스패치 수(과발행 방어)
FRESH_DAYS = 7         # 같은 이슈 지문 재트리거 금지 기간

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("breaking")


def _load_hist() -> dict:
    try:
        return json.load(open(HIST_PATH, encoding="utf-8"))
    except Exception:
        return {}


def _fetch_headlines(limit: int = 30) -> list[str]:
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        xml = r.read().decode("utf-8", "replace")
    titles = re.findall(r"<title>(?:<!\[CDATA\[)?([^<\]]+)", xml)
    # 첫 타이틀은 피드 자체 제목
    return [t.strip() for t in titles[1:limit + 1] if t.strip()]


def _judge(headlines: list[str], api_key: str) -> dict | None:
    """Gemini로 대형 이슈 판정. 반환: {issue, track, urgency, fingerprint} 또는 None."""
    from generator.content import _gen_text
    prompt = (
        "아래는 지금 구글뉴스 한국판 톱스토리 헤드라인 목록이다.\n"
        "여러 매체가 동시에 다루는 '대형 속보 이슈' 중, 다음 두 트랙에 해당하는 것이 있는지 판정하라.\n"
        "- track=tech: IT·테크·가전·AI·통신·게임 (예: 신제품 발표, AI 모델 공개, 대규모 장애, 리콜)\n"
        "- track=finance: 시장·금융에 큰 영향 (예: 지수 급등락, 금리 결정, 대형 기업 사건이 주가에 직결)\n"
        "정치·연예·스포츠·사건사고(위 두 트랙과 무관)는 제외.\n"
        "urgency는 1~5 (5=전 매체 집중 보도급). 해당 이슈가 없으면 urgency 0.\n"
        "fingerprint는 이슈를 대표하는 핵심 명사 2~3개를 붙인 소문자 슬러그(예: kimi-k3-반도체급락).\n"
        "JSON 한 줄만 출력: {\"issue\": \"이슈 한 줄\", \"track\": \"tech|finance\", "
        "\"urgency\": 0~5, \"fingerprint\": \"슬러그\"}\n\n[헤드라인]\n"
        + "\n".join(f"- {h}" for h in headlines)
    )
    raw = _gen_text(api_key, prompt, "너는 뉴스 데스크의 속보 판정 에디터다. JSON만 출력한다.", 512, 0.2)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        if d.get("track") in ("tech", "finance") and int(d.get("urgency", 0)) >= 4 and d.get("fingerprint"):
            return d
    except Exception as e:
        logger.warning(f"판정 파싱 실패: {e}")
    return None


def _dispatch(track: str, issue: str) -> bool:
    """GitHub API로 발행 워크플로 트리거 (GITHUB_TOKEN, actions:write 필요)."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "parky091999-sudo/hyunji_unni_blog")
    if not token:
        logger.error("GITHUB_TOKEN 없음 — 디스패치 불가")
        return False
    wf, inputs = ("tech_post.yml", {"fmt": "breaking", "force_post": "true"}) if track == "tech" \
        else ("stock_post.yml", {"force_post": "true"})
    body = json.dumps({"ref": "main", "inputs": inputs}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = r.status in (200, 204)
    except Exception as e:
        logger.error(f"디스패치 실패({wf}): {e}")
        return False
    logger.info(f"★속보 디스패치: {wf} ← {issue!r}")
    return ok


def run():
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        logger.error("GOOGLE_API_KEY 없음")
        return
    hist = _load_hist()
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    # 하루 상한
    todays = [v for v in hist.values() if isinstance(v, dict) and v.get("date") == today and v.get("dispatched")]
    if len(todays) >= DAILY_CAP:
        logger.info(f"오늘 디스패치 상한({DAILY_CAP}) 도달 — 스킵")
        return
    headlines = _fetch_headlines()
    if len(headlines) < 5:
        logger.warning("헤드라인 수집 부족 — 스킵")
        return
    verdict = _judge(headlines, api_key)
    if not verdict:
        logger.info("대형 이슈 없음 (urgency<4)")
        return
    fp = verdict["fingerprint"][:60]
    prev = hist.get(fp)
    if prev:
        try:
            prev_dt = datetime.fromisoformat(prev.get("at", ""))
            if now - prev_dt < timedelta(days=FRESH_DAYS):
                logger.info(f"이미 처리한 이슈({fp}) — 스킵")
                return
        except Exception:
            pass
    ok = _dispatch(verdict["track"], verdict.get("issue", ""))
    hist[fp] = {"date": today, "at": now.isoformat(), "issue": verdict.get("issue", ""),
                "track": verdict["track"], "urgency": verdict.get("urgency"), "dispatched": ok}
    json.dump(hist, open(HIST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    logger.info(f"기록 저장: {fp} (dispatched={ok})")


if __name__ == "__main__":
    run()
