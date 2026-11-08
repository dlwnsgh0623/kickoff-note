"""오늘 게시물을 한 화면에 모은 웹페이지 만들기 (GitHub Pages로 공개됨)
휴대폰에서 열어 [이미지 저장] [본문 복사] 버튼으로 바로 쓸 수 있어요.
"""
import html
import json
import os

from common import day_dir, load_posts, today

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>킥오프노트 {date}</title>
<style>
  :root {{ --bg:#0e0e0e; --card:#1a1a1a; --fg:#fff; --sub:#9a9a9a; --accent:#2ecc71; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,"Pretendard","Noto Sans KR",sans-serif; }}
  header {{ padding:20px 16px 8px; }}
  h1 {{ font-size:20px; margin:0; letter-spacing:-0.02em; }}
  h1 span {{ color:var(--sub); font-weight:400; font-size:14px; margin-left:8px; }}
  .tip {{ color:var(--sub); font-size:13px; margin:6px 0 0; line-height:1.5; }}
  .post {{ background:var(--card); margin:14px 16px; border-radius:16px; overflow:hidden; }}
  .slides {{ display:flex; overflow-x:auto; scroll-snap-type:x mandatory; -webkit-overflow-scrolling:touch; }}
  .slide {{ position:relative; flex:0 0 100%; scroll-snap-align:start; }}
  .slide img {{ width:100%; display:block; aspect-ratio:4/5; object-fit:cover; }}
  .slide .n {{ position:absolute; top:10px; right:10px; background:rgba(0,0,0,.6); padding:4px 10px; border-radius:20px; font-size:12px; }}
  .slide .dl {{ position:absolute; bottom:12px; right:12px; background:rgba(0,0,0,.65); color:#fff; padding:9px 14px;
               border-radius:20px; font-size:13px; font-weight:700; text-decoration:none; }}
  .meta {{ padding:12px 14px 0; font-size:13px; color:var(--sub); }}
  .hook {{ padding:6px 14px 0; font-weight:700; font-size:16px; line-height:1.35; }}
  textarea {{ width:100%; height:150px; margin:10px 0 0; padding:12px 14px; border:0; background:#111; color:#ddd;
             font-size:13px; line-height:1.5; resize:vertical; font-family:inherit; }}
  .btns {{ display:flex; gap:8px; padding:12px 14px 14px; }}
  .btns a, .btns button {{ flex:1; text-align:center; padding:13px 0; border-radius:12px; border:0; font-size:15px;
             font-weight:700; cursor:pointer; text-decoration:none; }}
  .save {{ background:#2b2b2b; color:#fff; }}
  .copy {{ background:var(--accent); color:#000; }}
  .copy.done {{ background:#1a8a4a; color:#fff; }}
  footer {{ color:var(--sub); font-size:12px; text-align:center; padding:10px 16px 30px; }}
</style></head><body>
<header>
  <h1>KICK/OFF <span>{date} · {n}개</span></h1>
  <p class="tip">사진은 옆으로 넘겨서 순서대로 저장하세요. 저장이 안 되면 사진을 길게 눌러 저장. 카톡 안에서 안 되면 오른쪽 위 메뉴 → '다른 브라우저로 열기'.</p>
</header>
{posts}
<footer>킥오프노트 자동 제작 · 올리기 전에 내용 한 번 확인!</footer>
<script>
async function copyText(btn, id) {{
  const ta = document.getElementById(id);
  try {{ await navigator.clipboard.writeText(ta.value); }}
  catch (e) {{ ta.focus(); ta.select(); document.execCommand('copy'); }}
  btn.textContent = '복사됨 ✓'; btn.classList.add('done');
  setTimeout(() => {{ btn.textContent = '본문 복사'; btn.classList.remove('done'); }}, 1800);
}}
</script>
</body></html>
"""

POST = """<section class="post" id="post{i}">
  <div class="slides">{slides}</div>
  <div class="meta">{i}/{n} · {league} · {outlets}곳 보도 · 사진 {count}장</div>
  <div class="hook">{hook}</div>
  <textarea id="cap{i}" readonly>{caption}</textarea>
  <div class="btns">
    <button class="copy" onclick="copyText(this,'cap{i}')">본문 복사</button>
  </div>
</section>"""

SLIDE = """<div class="slide"><img src="{img}" alt="" loading="lazy"><span class="n">{k}/{count}</span>
  <a class="dl" href="{img}" download="kickoff_{date}_{i}_{k}.jpg">저장</a></div>"""


def main():
    date = today()
    posts = load_posts(date) or []
    out = day_dir(date)
    blocks = []
    for i, p in enumerate(posts, 1):
        imgs = [f"{i}.jpg"] + [os.path.basename(x) for x in p.get("extra_paths", [])]
        slides = "".join(SLIDE.format(img=im, k=k, count=len(imgs), date=date, i=i) for k, im in enumerate(imgs, 1))
        blocks.append(POST.format(
            i=i, n=len(posts), slides=slides, count=len(imgs),
            league=html.escape(p.get("league", "")), outlets=p.get("outlets", ""),
            hook="<br>".join(html.escape(h) for h in p["hook"]),
            caption=html.escape(p["caption"]),
        ))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(PAGE.format(date=date, n=len(posts), posts="\n".join(blocks)))

    # output/ 로 들어오면 가장 최근 날짜로 이동
    os.makedirs("output", exist_ok=True)
    with open("output/index.html", "w", encoding="utf-8") as f:
        f.write(f'<meta http-equiv="refresh" content="0; url={date}/">')
    print(f"[페이지] output/{date}/index.html")


if __name__ == "__main__":
    main()
