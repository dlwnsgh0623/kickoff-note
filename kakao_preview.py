"""[제작 직후] 카카오톡 '나에게 보내기'로 오늘의 게시물 전송
게시물마다 메시지 1개: 카드 이미지 + 멘트 + [이미지 저장] [본문 복사] 버튼
"""
import json
import os

import requests

from common import load_posts, pages_url, public_url, today


def access_token():
    data = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    if os.environ.get("KAKAO_CLIENT_SECRET"):  # 클라이언트 시크릿을 켠 경우
        data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=15)
    r.raise_for_status()
    data = r.json()
    if "refresh_token" in data:
        print("[알림] 카카오 refresh token이 새로 발급됐어요. GitHub Secrets의 KAKAO_REFRESH_TOKEN을 바꿔주세요.")
    return data["access_token"]


def send(token, template):
    r = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"[카톡 실패] {r.status_code} {r.text}")


def _link(url):
    return {"web_url": url, "mobile_web_url": url}


def main():
    posts = load_posts()
    if not posts:
        print("오늘 게시물이 없어요")
        return
    token = access_token()

    page = pages_url(f"{today()}/")
    send(token, {
        "object_type": "text",
        "text": f"⚽ 킥오프노트 {today()} 게시물 {len(posts)}개 도착!\n\n아래 버튼을 누르면 5개가 한 화면에 나와요. 거기서 [이미지 저장] [본문 복사]를 쓰면 돼요.\n(카톡 안에서 저장이 안 되면 메뉴 → 다른 브라우저로 열기)",
        "link": _link(page),
        "button_title": "오늘 게시물 열기",
    })

    for i, p in enumerate(posts, 1):
        img = public_url(p["image_path"])
        txt = public_url(p["caption_path"])
        send(token, {
            "object_type": "feed",
            "content": {
                "title": f"[{i}/{len(posts)}] {p['league']} · 사진 {1 + len(p.get('extra_paths', []))}장",
                "description": f"{' '.join(p['hook'])}\n{p['caption'].splitlines()[0]}",
                "image_url": img,
                "link": _link(img),
            },
            "buttons": [
                {"title": "저장·복사 페이지", "link": _link(page + f"#post{i}")},
                {"title": "본문만 보기", "link": _link(txt)},
            ],
        })
    print("[카톡] 전송 완료")


if __name__ == "__main__":
    main()
