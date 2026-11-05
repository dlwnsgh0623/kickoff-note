"""카드 이미지 만들기: 사진 4:5 크롭 → 하단 페이드 → 흰 글씨 2줄 → 워드마크"""
import io
import os

import requests
from PIL import Image, ImageDraw, ImageFont

import settings

W, H = 1080, 1350
SIDE = 60  # 좌우 여백

FONT_CANDIDATES = [
    "fonts/Pretendard-Black.otf",  # fonts 폴더에 넣으면 이걸 우선 사용
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
]


def _font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size, index=1 if p.endswith(".ttc") else 0)
    raise FileNotFoundError("한글 글꼴을 찾지 못했어요")


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


def _fit_size(lines, max_size=84, min_size=56):
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for size in range(max_size, min_size - 1, -2):
        f = _font(size)
        if all(d.textlength(l, font=f) <= W - SIDE * 2 for l in lines):
            return size
    return min_size


def make_card(image_url, hook_lines, out_path):
    photo = _load_photo(image_url)
    img = _cover(photo) if photo else _fallback_bg()
    img = _fade(img)
    d = ImageDraw.Draw(img)

    size = _fit_size(hook_lines)
    f = _font(size)
    line_h = int(size * 1.32)
    y = H - 140 - line_h * len(hook_lines)
    for line in hook_lines:
        d.text((SIDE, y), line, font=f, fill="white")
        y += line_h

    d.text((W // 2, H - 58), settings.WORDMARK, font=_font(34), fill="white", anchor="mm")
    img.save(out_path, "JPEG", quality=92)  # 인스타는 JPEG만 받아요
    return bool(photo)
