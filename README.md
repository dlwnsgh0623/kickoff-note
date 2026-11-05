# 킥오프노트 (@kickoff.note) 게시물 자동 제작 프로그램

매일 해외축구 6개 리그(EPL·라리가·분데스·세리에A·리그1·사우디) 뉴스를
카카오(다음) 검색으로 모아 화제순 5개를 골라
카드 이미지와 설명글(본문)을 만들어 카카오톡으로 보내줍니다. 인스타 업로드는 직접 해요.

## 하루 흐름

| 한국 시간 | 하는 일 |
|---|---|
| 18:00 | 뉴스 수집 → 화제순 5개 선정 → 멘트·본문 작성 → 카드 이미지 제작 |
| 제작 직후 | 카톡으로 게시물 5개 전송 (각각 [이미지 저장] [본문 복사] 버튼) |
| 20:00 | 카톡에서 받아서 인스타에 직접 올리기 |

※ GitHub 서버 사정으로 몇 분~수십 분 늦게 시작될 때가 있어요.
시간을 바꾸려면 `.github/workflows/make.yml`의 `cron` 숫자를 바꾸세요 (한국 시간 - 9시간).

## 파일 설명
- `settings.py` — **바꿀 일 있으면 여기만 보면 돼요** (게시물 수, 검색어, RSS 사이트, 해시태그)
  - 화제 점수 = 다룬 언론사 수 (RSS 사이트를 추가하면 가산점 `RSS_BONUS`)
- 사진은 기사들의 대표 사진 후보를 모아 **사진 담당 Claude가 직접 보고** 고릅니다 (주인공이 맞는지, 다른 언론사 글자가 박혀 있지 않은지)
- `news.py` — 뉴스 수집·선정·글쓰기
- `card.py` — 카드 이미지
- `make_posts.py` — 위 과정을 순서대로 실행
- `kakao_preview.py` — 카톡 전송
- `output/날짜/` — 그날 만든 이미지(1~5.jpg)와 본문(1~5.txt)

## 처음 한 번 설정 (GitHub → Settings → Secrets and variables → Actions → New repository secret)

| 이름 | 어디서 받나 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | 내 컴퓨터 터미널에서 `claude setup-token` 실행 → 나온 토큰 (Claude 구독 사용) |
| `KAKAO_REST_KEY` | 카카오 디벨로퍼스 → 내 앱 → 앱 키 → REST API 키 (뉴스 검색 + 카톡 전송에 같이 씀) |
| `KAKAO_REFRESH_TOKEN` | 카카오 로그인(talk_message 동의)으로 발급 |

### 꼭 확인할 것
1. **저장소는 Public**이어야 해요. 카톡이 이미지를 공개 주소에서 가져가기 때문이에요.
2. 카카오 디벨로퍼스 → 내 앱 → 플랫폼 → Web 사이트 도메인에
   `https://raw.githubusercontent.com` 을 등록해야 카톡 버튼이 열려요.
3. Settings → Actions → General → Workflow permissions 를 **Read and write** 로.

> API 키로 돌리고 싶으면 `ANTHROPIC_API_KEY`를 추가하고 make.yml의 env에도 넣으면 자동으로 API를 써요.

## 테스트하기
Actions 탭 → `오늘의 게시물 만들기` → **Run workflow** 를 누르면 지금 바로 만들어서 카톡이 와요.
