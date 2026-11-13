"""특정 게시물만 다시 만들기
사용법: python redo.py "4=아르나우 오르티스 아틀레티코, 5"
  - 번호만 쓰면 그 게시물의 주제로 기사를 다시 찾아서 새로 만들어요
  - '번호=검색어'로 쓰면 그 검색어로 기사를 찾아서 만들어요 (주제가 틀렸을 때)
날짜는 KICKOFF_DATE(비우면 오늘) 게시물이 대상이에요.
"""
import glob
import os
import sys

import card
import news
import settings
from common import day_dir, load_posts, save_posts, today


def parse(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        num, _, query = part.partition("=")
        out.append((int(num.strip()), query.strip()))
    return out


def main():
    date = today()
    out = day_dir(date)
    posts = load_posts(date)
    if not posts:
        sys.exit(f"{date} 게시물이 없어요")

    changed = 0
    for num, query in parse(sys.argv[1] if len(sys.argv) > 1 else ""):
        if not 1 <= num <= len(posts):
            print(f"[건너뜀] {num}번 게시물이 없어요")
            continue
        old = posts[num - 1]
        query = query or old.get("subject") or old["topic"]
        print(f"[다시 만들기 {num}] 검색어: {query}")
        articles = news.search_articles(query)
        if not articles:
            print(f"[실패 {num}] '{query}' 관련 언론사 기사를 못 찾았어요 → 기존 게시물 유지")
            continue
        story = {"topic": query, "league": old.get("league", ""), "articles": articles,
                 "outlets": len({a["domain"] for a in articles})}
        others = [p["hook"] for i, p in enumerate(posts) if i != num - 1]
        style = settings.HOOK_STYLES[(num - 1) % len(settings.HOOK_STYLES)]
        try:
            post = news.write_post(story, style=style, used_hooks=others)
        except Exception as e:
            print(f"[실패 {num}] {type(e).__name__} {e} → 기존 게시물 유지")
            continue
        if not post["image_source"]:
            print(f"[주의 {num}] 표지 사진을 못 찾았어요")

        for f in glob.glob(os.path.join(out, f"{num}-*.jpg")):
            os.remove(f)
        path = os.path.join(out, f"{num}.jpg")
        card.make_card(post["image_source"], post["hook"], path, post.get("highlight", 2))
        post["image_path"] = path
        post["extra_paths"] = []
        for k, src in enumerate(post.get("extra_sources", []), 2):
            ep = os.path.join(out, f"{num}-{k}.jpg")
            if card.make_photo_slide(src, ep):
                post["extra_paths"].append(ep)
        post["caption_path"] = os.path.join(out, f"{num}.txt")
        with open(post["caption_path"], "w", encoding="utf-8") as f:
            f.write(post["caption"])
        posts[num - 1] = post
        changed += 1
        print(f"[완성 {num}] 사진 {1 + len(post['extra_paths'])}장 | {' / '.join(post['hook'])}")

    save_posts(posts, date)
    if not changed:
        sys.exit("다시 만든 게시물이 없어요 (카톡은 보내지 않아요)")


if __name__ == "__main__":
    main()
