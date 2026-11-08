"""카드 이미지 만들기: 사진 4:5 크롭 → 하단 페이드 → 흰 글씨 2줄 → 워드마크"""
import glob
import io
import os
import re

import requests
from PIL import Image, ImageDraw, ImageFont

import settings

W, H = 1080, 1350
SIDE = 60  # 좌우 여백

FONT_CANDIDATES = [
    "fonts/Pretendard-Black.otf",  # fonts 폴더에 넣으면 이걸 우선 사용
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
]
_FONT_PATH = None


def _find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    # 위치가 다른 서버를 대비해 직접 찾아보기
    for pattern in ("/usr/share/fonts/**/NotoSansCJK*Black*", "/usr/share/fonts/**/NotoSansCJK*Bold*",
                    "/usr/share/fonts/**/*CJK*Bold*"):
        found = sorted(glob.glob(pattern, recursive=True))
        if found:
            return found[0]
    raise FileNotFoundError("한글 글꼴을 찾지 못했어요")


def _font(size):
    global _FONT_PATH
    _FONT_PATH = _FONT_PATH or _find_font()
    p = _FONT_PATH
    # .ttc 묶음 파일에서 1번이 한국어(KR) 글꼴
    return ImageFont.truetype(p, size, index=1 if p.endswith(".ttc") else 0)


def _load_photo(url):
    if not url:
        return None
    if os.path.exists(url):  # 테스트용: 내 컴퓨터 파일
        return Image.open(url).convert("RGB")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img if img.width >= 400 else None
    except Exception as e:
        print(f"[사진 실패] {e}")
        return None


def _variants(url):
    """썸네일 주소면 원본 크기 주소부터 시도"""
    out = []
    v = re.sub(r"_v\d+(\.\w+)$", r"\1", url)                 # ..._v150.jpg → ....jpg
    v = v.replace("/news/thumbnail/", "/news/photo/")
    v = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", v)               # 워드프레스 ...-300x200.jpg
    if v != url:
        out.append(v)
    out.append(url)
    return out


def _is_real_photo(img):
    """글자만 있는 카드뉴스/로고 이미지 거르기: 흰 배경이 넓거나 너무 단조로우면 탈락"""
    g = img.convert("L").resize((64, 64))
    px = list(g.getdata())
    white = sum(1 for v in px if v > 235) / len(px)
    mean = sum(px) / len(px)
    std = (sum((v - mean) ** 2 for v in px) / len(px)) ** 0.5
    return white < 0.3 and std > 25


def _ahash(img):
    """사진 지문 (같은 사진이 다른 크기로 여러 기사에 쓰인 경우 걸러내기용)"""
    g = img.convert("L").resize((16, 16))
    px = list(g.getdata())
    avg = sum(px) / len(px)
    return [p > avg for p in px]


def _same_photo(a, b):
    return sum(x != y for x, y in zip(a, b)) < 20  # 256칸 중 20칸 미만 차이면 같은 사진


def photo_candidates(urls, max_n=6):
    """기본 검사(크기·카드뉴스 여부·중복)를 통과한 사진 후보들: [(주소, 이미지), ...]"""
    out, hashes = [], []
    for url in urls:
        for u in _variants(url):
            img = _load_photo(u)
            if img and img.width >= 600 and _is_real_photo(img):
                h = _ahash(img)
                if not any(_same_photo(h, x) for x in hashes):
                    out.append((u, img))
                    hashes.append(h)
                break
        if len(out) >= max_n:
            break
    return out


def _cover(img):
    """사진을 4:5로 꽉 채우게 자르기 (얼굴이 잘리지 않게 위쪽 기준)"""
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x = (img.width - W) // 2
    y = int((img.height - H) * 0.3)
    return img.crop((x, y, x + W, y + H))


def _fallback_bg():
    """사진을 못 구했을 때 쓰는 기본 배경 (진한 초록 그라데이션)"""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(10 + 20 * t), int(70 - 40 * t), int(40 - 20 * t)))
    return img


def _fade(img):
    mask = Image.new("L", (1, H))
    start, length = int(H * 0.45), H * 0.42
    for y in range(H):
        a = 0 if y < start else min(255, int(255 * ((y - start) / length) ** 1.3))
        mask.putpixel((0, y), a)
    return Image.composite(Image.new("RGB", (W, H)), img, mask.resize((W, H)))


def _fit_size(lines, max_size=96, min_size=60):
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(max_size, min_size - 1, -2):
        f = _font(size)
        if all(d.textlength(l, font=f) <= W - SIDE * 2 for l in lines):
            return size
    return min_size


def make_photo_slide(image_url, out_path):
    """표지 뒤에 붙는 추가 사진: 4:5로 자르고 아래에 워드마크만 살짝"""
    photo = _load_photo(image_url)
    if not photo:
        return False
    img = _cover(photo)
    mask = Image.new("L", (1, H))
    start = int(H * 0.82)
    for y in range(H):
        mask.putpixel((0, y), 0 if y < start else min(170, int(170 * (y - start) / (H - start))))
    img = Image.composite(Image.new("RGB", (W, H)), img, mask.resize((W, H)))
    ImageDraw.Draw(img).text((W // 2, H - 58), settings.WORDMARK, font=_font(34), fill="white", anchor="mm")
    img.save(out_path, "JPEG", quality=92)
    return True


def make_card(image_url, hook_lines, out_path, highlight=2):
    photo = _load_photo(image_url)
    img = _cover(photo) if photo else _fallback_bg()
    img = _fade(img)
    d = ImageDraw.Draw(img)

    size = _fit_size(hook_lines)
    f = _font(size)
    line_h = int(size * 1.28)
    y = H - 150 - line_h * len(hook_lines)
    for i, line in enumerate(hook_lines, 1):
        color = settings.HOOK_ACCENT if (settings.HOOK_ACCENT and i == highlight) else "white"
        d.text((SIDE, y), line, font=f, fill=color)
        y += line_h

    d.text((W // 2, H - 58), settings.WORDMARK, font=_font(34), fill="white", anchor="mm")
    img.save(out_path, "JPEG", quality=92)  # 인스타는 JPEG만 받아요
    return bool(photo)
