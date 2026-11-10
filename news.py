"""뉴스 수집 → 화제순 선정 → 멘트/설명글 작성"""
import base64
import html
import json
import os
import re
import subprocess
import tempfile
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
3) 서로 다른 언론사가 많이 다룬 이슈일수록 화제. 화제 순으로 {settings.POST_COUNT + 7}개를 골라.
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
    text = " ".join(p for p in paras if len(p) > 30)[:4000]
    if len(text) < 200:  # <p>가 없는 사이트 대비
        text = _clean(body)[:4000]
    image = _meta(page, "og:image")
    if image and image.count("http") > 1:  # 'https://cdn.../statichttps://img...' 같은 깨진 주소 보정
        image = "http" + image.split("http")[-1]
    return {
        "image": image,
        "site": _meta(page, "og:site_name"),
        "text": text,
    }


# ---------------- 5. 멘트 + 설명글 작성 ----------------
# ---------------- 사진 담당: 후보 사진을 Claude가 직접 보고 고르기 ----------------
PHOTO_PROMPT = """너는 해외축구 인스타 계정의 사진 담당이야.
게시물 주제: {topic}
이미지 문구: {hook}
주인공(선수/팀) 단서: {tags}

후보 사진 파일: {files}
각 사진을 직접 열어보고
1) 표지(cover): 이 게시물 첫 장에 가장 맞는 사진 하나
2) 추가(extras): 표지 뒤에 넘겨볼 관련 사진 최대 {n_extra}장 (표지와 다른 장면, 같은 이야기)
를 골라.

공통 조건
- 주제의 주인공 선수/팀이 나온 사진이어야 함 (다른 팀 유니폼이면 탈락). 선수 이야기면 그 선수 본인이 보여야 함.
- 다른 언론사의 제목·자막·로고·카드뉴스 글자가 크게 박힌 사진은 탈락 (작은 워터마크는 괜찮음)
- 표지는 인물이 크게, 선명하게 나온 사진 우선
- 추가 사진은 표지와 거의 같은 사진(같은 장면·같은 구도)이면 안 됨. 경기 장면, 세리머니, 감독, 관중 등 이야기를 보충하는 장면이면 좋음
- 맞는 표지가 없으면 cover는 0, 맞는 추가 사진이 없으면 extras는 빈 배열

JSON으로만 답해: {{"cover": 번호, "extras": [번호, ...], "reason": "짧은 이유"}}"""


def search_photos(query, n=12):
    """카카오 이미지 검색으로 사진 후보 보충 (뉴스 사진 위주)"""
    try:
        r = requests.get(
            "https://dapi.kakao.com/v2/search/image",
            headers={"Authorization": f"KakaoAK {os.environ['KAKAO_REST_KEY']}"},
            params={"query": query, "sort": "recency", "size": 40},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[이미지 검색 실패] {query}: {e}")
        return []
    out = []
    for d in r.json().get("documents", []):
        dom = urlparse(d.get("doc_url", "")).netloc.replace("www.", "")
        if any(w in dom for w in NON_NEWS):
            continue
        if d.get("width", 0) >= 700 and d.get("height", 0) >= 450:
            out.append(d["image_url"])
    return list(dict.fromkeys(out))[:n]


def pick_photo(story, post, urls):
    """기사 대표 사진 + 이미지 검색 사진을 모아 표지 1장과 추가 사진들을 고름.
    돌려주는 값: (표지 주소 또는 None, [추가 사진 주소들])"""
    query = " ".join(post["hashtags"][:2]) or story["topic"]
    searched = search_photos(query) if settings.EXTRA_PHOTOS or settings.PHOTO_SEARCH_FALLBACK else []
    cover, extras = _pick_from(story, post, list(dict.fromkeys(urls + searched)))
    return cover, extras


def _pick_from(story, post, urls):
    cands = card.photo_candidates(urls, max_n=10)
    if not cands:
        return None, []
    work = tempfile.mkdtemp(prefix="photos_")
    files = []
    for i, (_, img) in enumerate(cands, 1):
        small = img.copy()
        small.thumbnail((768, 768))
        name = f"c{i}.jpg"
        small.save(os.path.join(work, name), "JPEG", quality=85)
        files.append(name)
    prompt = PHOTO_PROMPT.format(topic=story["topic"], hook=" / ".join(post["hook"]),
                                 tags=", ".join(post["hashtags"]), files=", ".join(files),
                                 n_extra=settings.EXTRA_PHOTOS)
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            ans = _photo_api(prompt, work, files)
        else:
            r = subprocess.run(
                ["claude", "-p", "표준입력의 지시를 따라. Read 도구로 사진 파일들을 열어보고 JSON으로만 답해.",
                 "--model", settings.CLAUDE_CODE_MODEL, "--allowedTools", "Read", "--output-format", "text"],
                input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=900, cwd=work,
            )
            ans = json.loads(re.search(r"\{.*\}", r.stdout, re.S).group(0))
        n = int(ans.get("cover", ans.get("choice", 0)))
        ok = lambda k: isinstance(k, int) and 1 <= k <= len(cands)
        extras = [cands[k - 1][0] for k in ans.get("extras", []) if ok(k) and k != n][: settings.EXTRA_PHOTOS]
        print(f"[사진 선택] 후보 {len(cands)}장 → 표지 {n}번, 추가 {len(extras)}장 — {ans.get('reason', '')}")
        return (cands[n - 1][0] if ok(n) else None), extras
    except Exception as e:
        print(f"[사진 선택 실패] {e} → 첫 번째 후보 사용")
        return cands[0][0], []


def _photo_api(prompt, work, files):
    content = []
    for f in files:
        with open(os.path.join(work, f), "rb") as fh:
            content.append({"type": "text", "text": f})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                          "data": base64.b64encode(fh.read()).decode()}})
    content.append({"type": "text", "text": prompt})
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": settings.CLAUDE_MODEL, "max_tokens": 300,
              "messages": [{"role": "user", "content": content}]},
        timeout=180,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"])
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def _is_blog(site, domain):
    """언론사가 아닌 개인 블로그·커뮤니티인지"""
    text = f"{site or ''} {domain or ''}".lower()
    return any(w in text for w in ("블로그", "blog", "티스토리", "tistory", "카페", "cafe", "커뮤니티", "moonari"))


def _tidy(body):
    """단락 사이 빈 줄 하나로 정리 (AI가 줄바꿈을 들쭉날쭉하게 줄 때 대비)"""
    paras = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\n", body.strip()) if p.strip()]
    return "\n\n".join(paras)


def write_post(story, style="", used_hooks=()):
    details, candidates, sources = [], [], []
    for a in story["articles"][:7]:
        info = fetch_article(a["link"])
        if _is_blog(info.get("site"), a["domain"]):
            continue  # 개인 블로그는 글 재료·출처·사진에서 모두 제외
        if info.get("image"):
            candidates.append(info["image"])
        if len(details) < 4:  # 글은 언론사 기사 최대 4개로, 사진 후보는 최대 7개 기사에서
            sources.append(info.get("site") or a["domain"])
            details.append(f"[제목] {a['title']}\n[요약] {a['desc']}\n[본문] {info.get('text', '')}")
    style = style or settings.HOOK_STYLES[0]
    used = " | ".join(" / ".join(h) for h in used_hooks) or "(없음)"
    prompt = f"""너는 해외축구 인스타 계정 '킥오프노트' 운영자야. 아래 기사들만 근거로 게시물을 써.

규칙
- 기사에 없는 사실, 숫자, 인용은 절대 만들지 마. 애매하면 빼.
- 영어 기사는 한국어로 옮겨서 써. 선수·팀 이름은 한국에서 흔히 쓰는 표기로.
- hook: 이미지 위에 들어갈 2줄. 해외축구 커뮤니티(에펨코리아·해축갤)에서 조회수 터지는 글 제목처럼 써.
  톤 기준 — 아래 예시보다 더 커뮤체로, 하지만 내용 과장·왜곡은 금지:
    '결국 음바페 넘은 / 라민 야말 근황'  ← 이건 살짝 점잖은 편. 이것보다 더 입말로.
    '호날두 인류 최초 기록 / 단 15골 남았다'
    좋은 예: '이게 그 7연승 맨시티 맞음? / 노팅엄한테 1-3 처맞음', '케인 결국 뮌헨 잔류 / 발롱도르 들고 재계약',
            '김민재 2경기 연속 벤치 / 콤파니 진심인가', '리버풀 챔스 첫 패배 / 이스탄불 원정은 역시 지옥'
  구조: 1줄째 = 주인공+상황을 끊어 치는 짧은 구, 2줄째 = 펀치라인(반전·수치·팬 반응). 각 줄 한글 13자 이내.
  입말 허용: '~맞음?', '~임', '~함', '~래', '~하네', '~실화냐', '근황', '처맞음', '폼 미쳤다' 등 커뮤니티 어휘.
  추임새(ㅋㅋ, ㄷㄷ, ㅠㅠ, ;;)는 멘트 전체에서 최대 1개, 그리고 오늘 이미 쓴 추임새는 다시 쓰지 마.
  이번 게시물의 hook 스타일: {style}
  오늘 이미 쓴 멘트(같은 어미·구조·추임새 반복 금지): {used}
- highlight: hook 두 줄 중 강조(형광색)할 줄 번호. 보통 펀치라인 쪽(1 또는 2).
- caption_title: 설명란 첫 줄, 이모지 1개 포함, 30자 이내.
- caption_body: 실제 스포츠 기사처럼 충실하게, 존댓말 뉴스체. 분량은 공백 포함 900~1300자.
  가독성도 중요해: 휴대폰에서 읽기 편하게 단락을 나눠.
  · 5~7개 단락, 단락 사이는 빈 줄 하나(\n\n). 한 단락은 2~3문장, 단락 하나는 200자를 넘지 마.
  · 한 문장은 60자 안팎. '~했고, ~했지만, ~하며'처럼 이어 붙인 긴 문장은 반드시 쪼개.
  · 단락 구성(기사에 있는 내용만, 없는 항목은 건너뛰기):
    ① 리드: 무슨 일이 있었나 (결과·핵심 한 번에)
    ② 경기/사건 흐름: 득점 시간, 결정적 장면, 전개 순서
    ③ 주인공 활약·기록: 개인 기록, 수치, 비교 대상
    ④ 발언: 감독·선수 인터뷰 (따옴표로 인용, 기사에 있을 때만)
    ⑤ 배경·맥락: 최근 흐름, 순위, 이적설, 부상 등
    ⑥ 전망: 순위 변화, 다음 경기 일정과 상대
  · 여러 기사의 정보를 합쳐서 써. 기사에 없는 사실·숫자·인용은 절대 만들지 마.
  · 각 단락 첫머리에 그 단락에 맞는 이모지 1개 (예: ⚽ 📊 🗣️ 📈 🔜). 이모지 외 꾸밈 기호는 쓰지 마.
- hashtags: 선수·팀·감독·대회·라이벌팀 등 이 게시물과 관련된 태그 8~12개 (# 없이, 띄어쓰기 없이).

JSON으로만 답해:
{{"hook":["1줄","2줄"],"highlight":2,"caption_title":"...","caption_body":"단락1\\n\\n단락2\\n\\n단락3","hashtags":["..."]}}

기사들:
""" + "\n\n".join(details)
    post = ask_claude(prompt, max_tokens=4000)
    image, extra_images = pick_photo(story, post, list(dict.fromkeys(candidates)))

    # 해시태그: 기본 + 리그 + 게시물 관련 태그 (인스타 최대 30개)
    clean = lambda ts: [t.replace("#", "").replace(" ", "") for t in ts if t]
    base = clean(settings.BASE_HASHTAGS + settings.LEAGUE_HASHTAGS.get(story["league"], []))
    tags = list(dict.fromkeys(base + clean(post["hashtags"])))[: settings.MAX_HASHTAGS]
    src = ", ".join(list(dict.fromkeys(sources))[:2])
    tail = f"📰 출처: {src}\n📸 사진: 출처 기사\n\n{settings.ACCOUNT_HANDLE}\n" + " ".join("#" + t for t in tags)
    paras = _tidy(post["caption_body"]).split("\n\n")
    while True:  # 인스타 본문 한도 2200자: 넘으면 마지막 단락부터 빼기
        caption = f"{post['caption_title']}\n\n" + "\n\n".join(paras) + "\n\n" + tail
        if len(caption) <= 2200 or len(paras) <= 2:
            break
        paras = paras[:-1]
    return {
        "topic": story["topic"],
        "league": story["league"],
        "outlets": story["outlets"],
        "hook": post["hook"][:2],
        "highlight": int(post.get("highlight", 2)),
        "caption": caption[:2200],
        "image_source": image,
        "extra_sources": extra_images,
        "article_links": [a["link"] for a in story["articles"][:4]],
    }
