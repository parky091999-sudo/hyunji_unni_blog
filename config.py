import os
from dotenv import load_dotenv

load_dotenv()

# 네이버 계정 (Playwright 로그인용)
NAVER_ID      = os.getenv("NAVER_ID", "")       # 로그인 ID: gyhj1101
NAVER_PW      = os.getenv("NAVER_PW", "")
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "")  # 블로그 주소 ID: hyunji_unni
# GH Actions에서 쿠키 재사용 (JSON 문자열)
NAVER_COOKIES = os.getenv("NAVER_COOKIES", "")

# Google (Gemini)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Pexels (이미지)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Dirs
ROOT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT_DIR, "data")
LOG_DIR  = os.path.join(ROOT_DIR, "logs")
