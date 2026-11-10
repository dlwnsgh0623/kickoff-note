"""[매일 18:00] 오늘의 게시물 5개 만들기"""
import os
import sys
from datetime import datetime, timedelta

import card
import news
import settings
from common import KST, day_dir, load_posts, save_posts, today


def recent_topics(days=3):
    topics = []
    for i in range(1, days + 1):
        d = (datetime.now(KST) - timedelta(days=i)).strftime("%Y-%m-%d")
        for p in (load_posts(d) or []):
            topics.append(p["topic"])
    return topics


def main():
    date = today()
    out = day_dir(date)
    os.makedirs(out, exist_ok=True)

    articles = news.collect_articles()
    if not articles:
        sys.exit("기사를 하나도 못 모았어요. 카카오 REST 키를 확인해주세요.")

    stories = news.pick_stories(articles, recent_topics())
    print(f"[선정] 후보 {len(stories)}개")

    with_photo, without_photo = [], []
    for s in stories:
        if len(with_photo) >= settings.POST_COUNT:
            break
        style = settings.HOOK_STYLES[len(with_photo) % len(settings.HOOK_STYLES)]
        used = [p["hook"] for p in with_photo + without_photo]
        try:
            post = news.write_post(s, style=style, used_hooks=used)
        except Exception as e:
            print(f"[작성 실패] {s['topic']}: {e}")
            continue
        (with_photo if post["image_source"] else without_photo).append(post)
        if not post["image_source"]:
            print(f"[사진 없음] {s['topic']}")

    # 표지 사진이 있는 게시물만 사용. 그래도 모자란 날에만 사진 없는 게시물로 채우고 카톡에 표시
    posts = (with_photo + without_photo)[: settings.POST_COUNT]
    if len(with_photo) < settings.POST_COUNT:
        print(f"[주의] 표지 사진을 찾은 게시물이 {len(with_photo)}개뿐이에요")
    for i, p in enumerate(posts, 1):
        path = os.path.join(out, f"{i}.jpg")
        card.make_card(p["image_source"], p["hook"], path, p.get("highlight", 2))
        p["image_path"] = path
        # 표지 뒤 관련 사진: 1-2.jpg, 1-3.jpg ...
        p["extra_paths"] = []
        for k, src in enumerate(p.get("extra_sources", []), 2):
            ep = os.path.join(out, f"{i}-{k}.jpg")
            if card.make_photo_slide(src, ep):
                p["extra_paths"].append(ep)
        # 본문은 따로 텍스트 파일로도 저장 (카톡에서 열어서 복사하기 쉽게)
        p["caption_path"] = os.path.join(out, f"{i}.txt")
        with open(p["caption_path"], "w", encoding="utf-8") as f:
            f.write(p["caption"])
        print(f"[완성 {i}] {p['outlets']}곳 보도 | 사진 {1 + len(p['extra_paths'])}장 | {' / '.join(p['hook'])}")

    save_posts(posts, date)
    if len(posts) < settings.POST_COUNT:
        print(f"[주의] {len(posts)}개만 만들었어요")


if __name__ == "__main__":
    main()
