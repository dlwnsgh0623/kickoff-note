"""뉴스 수집 → 화제순 선정 → 멘트/설명글 작성"""
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

import settings

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; KickoffNoteBot/1.0)"}


# ---------------- 1. 수집 ----------------
def _clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def collect_articles():
    """네이버 뉴스 검색 API로 최근 기사를 모읍니다."""
    headers = {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }
    since = datetime.now(KST) - timedelta(hours=settings.NEWS_WITHIN_HOURS)
    seen_links, seen_titles, articles = set(), set(), []

    for q in settings.SEARCH_QUERIES:
        try:
            r = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                headers=headers,
                params={"query": q, "display": 100, "sort": "date"},
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"[수집 실패] {q}: {e}")
            continue

        for it in r.json().get("items", []):
            try:
                pub = parsedate_to_datetime(it["pubDate"])
            except Exception:
                continue
            if pub < since:
                continue
            link = it.get("originallink") or it.get("link")
            title = _clean(it["title"])
            key = re.sub(r"\W", "", title)[:30]
            if link in seen_links or key in seen_titles:
                continue
            seen_links.add(link)
            seen_titles.add(key)
            articles.append({
                "id": len(articles),
                "title": title,
                "desc": _clean(it.get("description")),
                "link": link,
                "naver_link": it.get("link"),
                "domain": urlparse(link).netloc.replace("www.", ""),
            })
    print(f"[수집] 기사 {len(articles)}개")
    return articles[:700]


# ---------------- 2. Claude 호출 ----------------
def ask_claude(prompt, max_tokens=4000):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"])
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))


# ---------------- 3. 화제순 선정 ----------------
def pick_stories(articles, recent_titles):
    lines = "\n".join(f"{a['id']}|{a['domain']}|{a['title']}" for a in articles)
    recent = "\n".join(f"- {t}" for t in recent_titles) or "(없음)"
    prompt = f"""너는 해외축구 뉴스 에디터야. 아래는 최근 24시간 한국 기사 목록이야 (형식: 번호|언론사|제목).

1) 같은 사건/이슈를 다룬 기사끼리 묶어.
2) 대상: 프리미어리그, 라리가, 분데스리가, 세리에A, 리그1, 사우디 프로리그 소속 팀·선수 이야기
   (이 리그 팀이 뛰는 챔피언스리그/유로파리그 경기도 포함). 그 외 리그, K리그, 국가대표, 광고성 기사는 제외.
3) 서로 다른 언론사가 많이 다룬 이슈일수록 화제. 화제 순으로 {settings.POST_COUNT + 3}개를 골라.
4) 최근 이미 올린 이슈와 같은 내용은 제외:
{recent}

JSON으로만 답해:
{{"stories":[{{"topic":"이슈 한줄 요약","league":"프리미어리그|라리가|분데스리가|세리에A|리그1|사우디 프로리그","article_ids":[번호들]}}]}}

기사 목록:
{lines}"""
    stories = ask_claude(prompt)["stories"]
    by_id = {a["id"]: a for a in articles}
    for s in stories:
        s["articles"] = [by_id[i] for i in s["article_ids"] if i in by_id]
        s["outlets"] = len({a["domain"] for a in s["articles"]})
    stories = [s for s in stories if s["articles"]]
    stories.sort(key=lambda s: s["outlets"], reverse=True)
    return stories


# ---------------- 4. 기사 페이지에서 사진/본문 가져오기 ----------------
def _meta(page, prop):
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']+)', page, re.I
    ) or re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{prop}["\']', page, re.I
    )
    return html.unescape(m.group(1)) if m else None


def fetch_article(url):
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.encoding = r.apparent_encoding or r.encoding
        page = r.text
    except Exception:
        return {}
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", page)
    paras = [_clean(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", body)]
    text = " ".join(p for p in paras if len(p) > 30)[:2500]
    if len(text) < 200:  # <p>가 없는 사이트 대비
        text = _clean(body)[:2500]
    return {
        "image": _meta(page, "og:image"),
        "site": _meta(page, "og:site_name"),
        "text": text,
    }


# ---------------- 5. 멘트 + 설명글 작성 ----------------
def write_post(story):
    details, image, sources = [], None, []
    for a in story["articles"][:4]:
        info = fetch_article(a["link"])
        if not image and info.get("image"):
            image = info["image"]
        sources.append(info.get("site") or a["domain"])
        details.append(f"[제목] {a['title']}\n[요약] {a['desc']}\n[본문] {info.get('text', '')}")

    prompt = f"""너는 해외축구 인스타 계정 '킥오프노트' 운영자야. 아래 기사들만 근거로 게시물을 써.

규칙
- 기사에 없는 사실, 숫자, 인용은 절대 만들지 마. 애매하면 빼.
- hook: 이미지 위에 들어갈 2줄. 해외축구 커뮤니티 말투(반말, ㅋㅋ/ㄷㄷ 가능)로 시선을 끌되 내용이 과장·왜곡되면 안 됨.
  1줄째는 주인공(선수/팀), 2줄째는 사건. 각 줄 한글 14자 이내.
- caption_title: 설명란 첫 줄, 이모지 1개 포함, 30자 이내.
- caption_body: 무슨 일이 있었는지 3~5문장, 존댓말 뉴스체. 핵심 기록/스코어가 있으면 포함.
- hashtags: 선수·팀 이름 등 3~5개 (# 없이).

JSON으로만 답해:
{{"hook":["1줄","2줄"],"caption_title":"...","caption_body":"...","hashtags":["..."]}}

기사들:
""" + "\n\n".join(details)
    post = ask_claude(prompt, max_tokens=1500)

    tags = settings.BASE_HASHTAGS + settings.LEAGUE_HASHTAGS.get(story["league"], []) + post["hashtags"]
    tags = list(dict.fromkeys(t.replace("#", "").replace(" ", "") for t in tags))
    src = ", ".join(list(dict.fromkeys(sources))[:2])
    caption = (
        f"{post['caption_title']}\n\n{post['caption_body']}\n\n"
        f"📰 출처: {src}\n📸 사진: 출처 기사\n\n"
        f"{settings.ACCOUNT_HANDLE}\n" + " ".join("#" + t for t in tags)
    )
    return {
        "topic": story["topic"],
        "league": story["league"],
        "outlets": story["outlets"],
        "hook": post["hook"][:2],
        "caption": caption[:2200],
        "image_source": image,
        "article_links": [a["link"] for a in story["articles"][:4]],
    }
