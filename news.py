"""뉴스 수집 → 화제순 선정 → 멘트/설명글 작성"""
import html
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

import card
import settings

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; KickoffNoteBot/1.0)"}


# ---------------- 1. 수집 ----------------
def _clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


# 뉴스가 아닌 사이트(블로그·커뮤니티 등)는 제외
NON_NEWS = ("tistory", "blog", "cafe", "namu.wiki", "wikipedia", "youtube", "instagram",
            "facebook", "x.com", "twitter", "fmkorea", "dcinside", "ruliweb", "clien",
            "theqoo", "inven", "brunch", "velog", "github", "reddit")


def collect_articles():
    """카카오(다음) 웹문서 검색 API로 최근 기사를 모읍니다."""
    headers = {"Authorization": f"KakaoAK {os.environ['KAKAO_REST_KEY']}"}
    since = datetime.now(KST) - timedelta(hours=settings.NEWS_WITHIN_HOURS)
    seen_links, seen_titles, articles = set(), set(), []

    for q in settings.SEARCH_QUERIES:
        for page in (1, 2):
            try:
                r = requests.get(
                    "https://dapi.kakao.com/v2/search/web",
                    headers=headers,
                    params={"query": q, "sort": "recency", "size": 50, "page": page},
                    timeout=15,
                )
                r.raise_for_status()
            except Exception as e:
                print(f"[수집 실패] {q}: {e}")
                break

            docs = r.json().get("documents", [])
            too_old = False
            for it in docs:
                try:
                    pub = datetime.fromisoformat(it["datetime"])
                except Exception:
                    continue
                if pub < since:
                    too_old = True
                    continue
                link = it["url"]
                domain = urlparse(link).netloc.replace("www.", "")
                if any(w in domain for w in NON_NEWS):
                    continue
                title = _clean(it["title"])
                key = re.sub(r"\W", "", title)[:30]
                if link in seen_links or key in seen_titles:
                    continue
                seen_links.add(link)
                seen_titles.add(key)
                articles.append({
                    "id": len(articles),
                    "title": title,
                    "desc": _clean(it.get("contents")),
                    "link": link,
                    "domain": domain,
                })
            if too_old or len(docs) < 50:
                break
    print(f"[수집] 카카오 검색 기사 {len(articles)}개")
    articles = articles[:650]

    rss = collect_rss()
    for a in rss:
        if a["link"] not in seen_links:
            a["id"] = len(articles)
            articles.append(a)
    print(f"[수집] 전체 {len(articles)}개 (RSS {len(rss)}개 포함)")
    return articles


def it_date(it):
    return (it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip()


def _parse_date(text):
    if not text:
        return None
    for f in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            d = f(text)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def collect_rss():
    """Score90 등 RSS 피드에서 최근 기사를 모읍니다. 실패해도 전체가 멈추지 않아요."""
    since = datetime.now(KST) - timedelta(hours=settings.NEWS_WITHIN_HOURS)
    out = []
    for feed in settings.RSS_FEEDS:
        for page in (1, 2, 3):
            url = feed if page == 1 else f"{feed}?paged={page}"
            try:
                r = requests.get(url, headers=UA, timeout=20)
                r.raise_for_status()
                root = ET.fromstring(r.content)
            except Exception as e:
                if page == 1:
                    print(f"[RSS 실패] {feed}: {e}")
                break
            items = root.findall(".//item")
            if page == 1:
                print(f"[RSS] {feed}: 피드 글 {len(items)}개")
            old = False
            if page == 1 and items:
                print(f"[RSS] 첫 글 날짜: {it_date(items[0])!r}")
            for it in items:
                pub = _parse_date(it_date(it))
                if not pub:
                    continue
                if pub < since:
                    old = True
                    continue
                link = (it.findtext("link") or "").strip()
                out.append({
                    "title": _clean(it.findtext("title")),
                    "desc": _clean(it.findtext("description"))[:300],
                    "link": link,
                    "domain": urlparse(link).netloc.replace("www.", ""),
                    "priority": True,
                })
            if old or not items:
                break
    return out


# ---------------- 2. Claude 호출 ----------------
def _claude_code(prompt):
    """Claude Code(구독 토큰)로 답 받기"""
    r = subprocess.run(
        ["claude", "-p", "표준입력으로 받은 지시를 그대로 따르고, 도구는 쓰지 말고, 요청한 JSON으로만 답해.",
         "--model", settings.CLAUDE_CODE_MODEL, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Claude Code 실행 실패: {r.stderr[:500]}")
    return r.stdout


def _claude_api(prompt, max_tokens):
    """Claude API 키로 답 받기"""
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
    return "".join(b.get("text", "") for b in r.json()["content"])


def ask_claude(prompt, max_tokens=4000):
    # API 키가 있으면 API, 없으면 Claude Code(구독)로
    if os.environ.get("ANTHROPIC_API_KEY"):
        text = _claude_api(prompt, max_tokens)
    else:
        text = _claude_code(prompt)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"Claude 답변에서 JSON을 못 찾았어요: {text[:300]}")
    return json.loads(m.group(0))


# ---------------- 3. 화제순 선정 ----------------
def pick_stories(articles, recent_titles):
    lines = "\n".join(f"{a['id']}|{a['domain']}|{a['title']}" for a in articles)
    recent = "\n".join(f"- {t}" for t in recent_titles) or "(없음)"
    prompt = f"""너는 해외축구 뉴스 에디터야. 아래는 최근 24시간 기사 목록이야 (형식: 번호|언론사|제목). 한국 기사와 영어 기사(score90.com 등)가 섞여 있어.

1) 같은 사건/이슈를 다룬 기사끼리 묶어. 한국 기사와 영어 기사도 같은 이슈면 한 묶음으로.
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
        # 화제 점수 = 보도한 언론사 수 + (지정 RSS 사이트가 다뤘으면 가산점)
        s["score"] = s["outlets"] + (settings.RSS_BONUS if any(a.get("priority") for a in s["articles"]) else 0)
        # 사진·본문은 지정 RSS 사이트 기사를 먼저 쓰도록 앞으로
        s["articles"].sort(key=lambda a: not a.get("priority"))
    stories = [s for s in stories if s["articles"]]
    stories.sort(key=lambda s: s["score"], reverse=True)
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
    details, candidates, sources = [], [], []
    for n, a in enumerate(story["articles"][:7]):
        info = fetch_article(a["link"])
        if info.get("image"):
            candidates.append(info["image"])
        if n < 4:  # 글은 앞 4개 기사로, 사진 후보는 최대 7개 기사에서
            sources.append(info.get("site") or a["domain"])
            details.append(f"[제목] {a['title']}\n[요약] {a['desc']}\n[본문] {info.get('text', '')}")
    image = card.choose_photo(list(dict.fromkeys(candidates)))

    prompt = f"""너는 해외축구 인스타 계정 '킥오프노트' 운영자야. 아래 기사들만 근거로 게시물을 써.

규칙
- 기사에 없는 사실, 숫자, 인용은 절대 만들지 마. 애매하면 빼.
- 영어 기사는 한국어로 옮겨서 써. 선수·팀 이름은 한국에서 흔히 쓰는 표기로.
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
