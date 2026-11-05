"""여러 파일에서 같이 쓰는 도구들"""
import json
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def today():
    return datetime.now(KST).strftime("%Y-%m-%d")


def day_dir(date=None):
    return os.path.join("output", date or today())


def load_posts(date=None):
    path = os.path.join(day_dir(date), "posts.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_posts(posts, date=None):
    os.makedirs(day_dir(date), exist_ok=True)
    with open(os.path.join(day_dir(date), "posts.json"), "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def public_url(path):
    """GitHub 저장소에 올라간 파일의 공개 주소 (인스타·카톡이 이미지를 가져갈 주소)"""
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path.replace(os.sep, '/')}"

