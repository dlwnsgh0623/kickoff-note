"""제작이 실패하면 카톡으로 알려주기"""
import os

from kakao_preview import access_token, send


def main():
    run = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    send(access_token(), {
        "object_type": "text",
        "text": "⚠️ 킥오프노트 오늘 게시물 제작이 실패했어요.\n\nClaude한테 '오늘 카톡 안 왔어'라고 말하면 원인 찾아서 다시 보내줄게요.\n(아래 버튼: 실행 기록)",
        "link": {"web_url": run, "mobile_web_url": run},
        "button_title": "실행 기록 보기",
    })
    print("[카톡] 실패 알림 전송")


if __name__ == "__main__":
    main()
