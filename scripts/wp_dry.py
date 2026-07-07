"""
워드프레스 심층분석 DRY_RUN — 발행 없이 생성→렌더→HTML 아티팩트만 (WP_PIPELINE §5 A단계).
GH Actions에서 GOOGLE_API_KEY로 실제 생성 품질을 검증한다. 로컬은 키가 없어 불가.

실행: WP_TOPIC=isa python -m scripts.wp_dry
결과: data/screenshots/wp_dry_<slug>.html (아티팩트 업로드) — 브라우저로 품질·렌더 검토
"""
import logging
import os
import sys

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import GOOGLE_API_KEY, DATA_DIR
from generator.deep_content import generate_deep_post
from generator.wp_render import render_wordpress_post

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_dry")

# 프로토타입 팩트 블록 — 프로덕션에선 constants_2026.yml + 데이터 수집기가 채운다.
TOPICS = {
    "isa": {
        "keyword": "ISA 계좌 비교",
        "category": "금융·재테크",
        "facts": {
            "제도": "ISA(개인종합자산관리계좌)",
            "납입한도": "연 2,000만원 (5년 누적 최대 1억원, 미납분 이월 가능)",
            "의무가입기간": "3년",
            "비과세한도_일반형": "200만원",
            "비과세한도_서민형": "400만원 (총급여 5,000만원 또는 종합소득 3,800만원 이하)",
            "초과수익_과세": "9.9% 분리과세 (일반 이자·배당소득세 15.4%보다 저율)",
            "계좌유형": ["신탁형", "일임형", "중개형(투자중개형)"],
            "가입자격": "만 19세 이상 거주자, 직전연도 금융소득종합과세 대상자는 제외",
            "연금계좌_전환혜택": "만기 자금을 연금저축·IRP로 이체 시 이체액의 10%(최대 300만원) 추가 세액공제",
        },
        "key_stats": [
            ("2,000만원", "연 납입 한도"),
            ("3년", "최소 의무가입"),
            ("9.9%", "초과수익 분리과세율"),
            ("400만원", "서민형 비과세 한도"),
        ],
    },
}


def _doc(title, r):
    css = """
:root{--fg:#1f2328;--muted:#6a737d;--line:#e5e7eb;--accent:#2f6f4f;--accent-bg:#eef6f1;--tableh:#f3f5f7;--soft:#fafbfc}
*{box-sizing:border-box}body{margin:0;background:#f3f4f6;color:var(--fg);font-family:'Malgun Gothic',system-ui,sans-serif;line-height:1.75}
.mocknote{max-width:800px;margin:14px auto 0;padding:9px 14px;border:1px dashed #b9c0c7;border-radius:8px;background:#fff;color:#6a737d;font-size:12.5px}
.wrap{max-width:800px;margin:12px auto 48px;background:#fff;padding:40px 44px 48px;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.crumb{font-size:13px;color:var(--muted);margin-bottom:14px}.crumb .here{color:var(--accent);font-weight:600}
h1{font-size:28px;line-height:1.38;margin:4px 0 12px}
.metaline{color:var(--muted);font-size:13px;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:22px}.metaline b{color:#414852}
.hj-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0}
.hj-stat{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:13px 8px;text-align:center}
.hj-stat-v{font-size:19px;font-weight:800;color:var(--accent)}.hj-stat-l{font-size:12px;color:var(--muted);margin-top:3px;line-height:1.4}
.hj-toc{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:20px 0}
.hj-toc-t{font-size:13px;font-weight:800;color:#414852;margin-bottom:8px}.hj-toc ol{margin:0;padding-left:20px}.hj-toc li{margin:4px 0;font-size:14.5px}.hj-toc a{color:#2b5a86;text-decoration:none}
.wrap p{margin:0 0 16px;font-size:16.5px}
.wrap h2{font-size:21.5px;border-top:1px solid var(--line);margin-top:34px;padding-top:26px;margin-bottom:13px}
.wrap ul,.wrap ol{margin:0 0 17px;padding-left:22px}.wrap li{margin:0 0 8px;font-size:16.5px}
.hj-summary{background:var(--accent-bg);border-left:4px solid var(--accent);border-radius:8px;padding:17px 21px;margin:24px 0}
.hj-summary-title{font-weight:800;color:var(--accent);margin:0 0 9px!important;font-size:14.5px}.hj-summary ul{margin:0;padding-left:2px;list-style:none}
.hj-summary li{position:relative;padding-left:23px;margin-bottom:7px;font-size:15.5px}.hj-summary li:before{content:'✓';position:absolute;left:0;color:var(--accent);font-weight:800}
.hj-table{margin:22px 0;overflow-x:auto}.hj-table table{border-collapse:collapse;width:100%;font-size:14.5px;min-width:520px}
.hj-table th,.hj-table td{border:1px solid var(--line);padding:10px 12px;text-align:left}.hj-table thead th{background:var(--tableh);font-weight:700}.hj-table tbody td:first-child{font-weight:600;background:var(--soft)}
.hj-faq-item{border:1px solid var(--line);border-radius:10px;padding:15px 19px;margin-bottom:11px}.hj-faq-q{margin:0 0 7px;font-size:15.5px;color:var(--accent)}.hj-faq-a{margin:0;color:#33393f;font-size:15.5px}
.hj-photo{margin:20px 0;border:1px dashed #c7ccd1;border-radius:8px;height:120px;display:flex;align-items:center;justify-content:center;color:#9aa0a6;font-size:13px;background:var(--soft)}.hj-photo:after{content:'[이미지 슬롯]'}
.hj-sources{margin-top:34px}.hj-sources h2{font-size:16px;border:0;padding:0;margin:0 0 10px}.hj-sources ul{padding-left:20px}.hj-sources li{font-size:14px;margin-bottom:6px}.hj-sources a{color:#2b5a86}
.hj-disclaimer{margin-top:20px;background:#fbf7ee;border:1px solid #ecdfc3;border-radius:10px;padding:14px 18px;font-size:13.5px;color:#6d5f43;line-height:1.65}
@media(max-width:640px){.wrap{padding:24px 16px}.hj-stats{grid-template-columns:1fr 1fr}h1{font-size:22px}}
"""
    return (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{r["seo_title"]}</title><meta name="description" content="{r["meta_description"]}">'
        f'{r["schema_jsonld"]}<style>{css}</style></head><body>'
        f'<div class="mocknote">◇ WP 심층분석 <b>DRY_RUN</b>(자동 생성) — deep_content + wp_render 실제 산출 · 발행 안 함</div>'
        f'<article class="wrap"><nav class="crumb"><span>홈</span> › <span class="here">{r["tags"][0] if r["tags"] else ""}</span></nav>'
        f'<h1>{title}</h1><div class="metaline">글 <b>현지언니</b> · 게시 2026.07.07 · 심층분석</div>'
        f'{r["content_html"]}</article></body></html>'
    )


def run():
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료(로컬은 GH Actions로 실행)")
        sys.exit(1)
    topic_id = os.environ.get("WP_TOPIC", "isa").strip().lower()
    topic = TOPICS.get(topic_id)
    if not topic:
        logger.error(f"알 수 없는 WP_TOPIC: {topic_id!r} (가능: {list(TOPICS)})")
        sys.exit(1)

    logger.info(f"[DRY_RUN] 심층분석 생성 시작: {topic_id}")
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("생성 실패 — 종료")
        sys.exit(1)

    r = render_wordpress_post(post, category=topic["category"])
    logger.info(f"제목: {post['title']}")
    logger.info(f"slug: {r['slug']}")
    logger.info(f"content_html {len(r['content_html'])}자 · 목차 {'있음' if r['toc_html'] else '없음'} · "
                f"핵심수치 {'있음' if r['key_stats_html'] else '없음'} · 출처 {'있음' if r['sources_html'] else '없음'}")

    out_dir = os.path.join(DATA_DIR, "screenshots")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"wp_dry_{r['slug']}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(_doc(post["title"], r))
    logger.info(f"[DRY_RUN] HTML 저장: {out}")
    logger.info("===== 본문(마커) =====\n" + post.get("body", "")[:800] + "\n=====")


if __name__ == "__main__":
    run()
