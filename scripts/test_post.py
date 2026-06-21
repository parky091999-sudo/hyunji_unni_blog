"""
Playwright 포스팅 로직만 단독 테스트 (Gemini 생략)
로컬에서: python -m scripts.test_post
"""
import asyncio
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES
from poster.naver_blog import post_to_naver_blog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

TEST_TITLE = "🧪 테스트 포스팅 — 자동화 확인용"
TEST_BODY = """현지언니 블로그 자동화 테스트 중이에요 😊

【테스트 내용】
✔ Playwright 에디터 진입 확인
✔ 제목/본문 입력 확인
✔ 발행 버튼 동작 확인

잘 보이면 성공이에요! 나중에 이 포스팅은 삭제할게요 🙂"""
TEST_TAGS = ["테스트", "자동화확인"]


if __name__ == "__main__":
    print(f"NAVER_ID: {NAVER_ID}")
    print(f"NAVER_BLOG_ID: {NAVER_BLOG_ID}")
    print(f"쿠키 있음: {'예' if NAVER_COOKIES else '아니오'}")
    print("-" * 50)

    result = post_to_naver_blog(
        naver_id=NAVER_ID,
        naver_pw=NAVER_PW,
        blog_id=NAVER_BLOG_ID or NAVER_ID,
        title=TEST_TITLE,
        body=TEST_BODY,
        tags=TEST_TAGS,
        naver_cookies=NAVER_COOKIES,
    )

    if result:
        print(f"\n✅ 포스팅 성공! URL: {result.get('post_url')}")
    else:
        print("\n❌ 포스팅 실패 — 스크린샷 확인: data/screenshots/")
