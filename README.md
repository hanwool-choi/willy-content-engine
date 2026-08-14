# 최윌리 옷장연구소 — 콘텐츠 엔진

Threads 채널 `@choi.willy.lab` 의 `[내일 뭐입지?]` 콘텐츠를 반자동으로
기획·생성하는 로컬 도구.

**내일 하루치**, 성별당 2픽(총 4장)을 수집해 서울 날씨에 맞춰 배정하고,
채널 말투로 게시용 텍스트 3종을 뽑아준다.

**공개 보드: https://hanwool-choi.github.io/willy-content-engine/**
(매일 08:00 KST 자동 갱신 — PC를 켜둘 필요 없다)

화면은 탭 두 개다.

- **[내일 뭐입지?]** — 날씨에 맞춘 내일의 코디 픽과 게시용 텍스트
- **[콘텐츠 아이디어 보울]** — 패션 신소식·할인 정보를 모아 보고, 고른
  항목을 채널 말투의 텍스트로 바꾼다

## 동작 방식

```
[내일 뭐입지?]
수집(16장) → 배치 분석(비전 1콜) → 배정(남2·여2) → 텍스트 3종

[콘텐츠 아이디어 보울]
7개 소스 수집(60~70건) → 반응 뱃지 → 선택 → 상세 본문 → 텍스트 3종
                                                    ↓
                        이미지·영상 생성과 업로드는 사용자가 별도 엔진에서 수동
```

- 비전 분석은 사진 전부를 **요청 1번**에 넣는 배치라 수십 초면 끝난다.
  (룩마다 한 번씩 부르던 초기 구조는 무료 티어 한도에 걸려 5~10분씩 걸렸다.)
- 날씨에 맞는 룩이 모자라면(예: 여름 소나기 예보) 빈 칸 대신 차선 룩을
  **"조건부 추천"** 사유와 함께 채워두고, 쓸지 뺄지는 사람이 정한다.
- 분석이 실패하면(한도·장애) 멈추지 않고 **분석 생략 모드**로 완주한다.
  성별이 URL로 보장되는 소스로 칸을 채우고 전부 "직접 확인" 표시를 단다.
- 이미지 생성·폴더 산출 코드(`generator/`, `publisher/folders.py`)는 남아
  있지만 현재 UI 흐름에서는 쓰지 않는다.

## 수집 대상

소스별 수집량은 `config.SOURCE_QUOTAS`에 있다 (합계 16장).

| 소스 | 장수 | 성격 |
|---|---|---|
| 무신사 스냅 (스냅 탭) | 8 | 국내 유저 스트릿, 주력 |
| WEAR.jp WEARISTA men/women | 2+2 | 일본 시티보이·미니멀, 성별 보장 |
| 유니클로 스타일링북 women/men | 2+2 | 베이직, 성별 보장 |

- 무신사는 자체 AI 코디를 피드에 섞어 내보낸다. 분석이 `is_ai`로 판정해
  **성별당 1장까지만** 남기고 초과분을 뺀다 (화면에 `AI` 배지 표시).
  `/snap/main/today` 랜딩은 AI 코디로 도배돼 있어 쓰면 안 된다.
- 유니클로·WEAR는 링크를 상대경로로 준다. 게시 페이지에서
  `config.SOURCE_ORIGINS`로 절대 URL로 되돌린다.
- 에이블리·크림은 각각 봇 차단(CAPTCHA)과 robots.txt 미제공으로 의도적으로
  제외했다. W컨셉은 robots가 화이트리스트 방식이라 제외.

수집은 **사람이 버튼을 누를 때**(로컬 앱)와 **매일 아침 배치**에서만
실행된다. 상시 순회 크롤링은 하지 않는다.

### 콘텐츠 아이디어 보울 소스 (7곳)

정의는 `src/willy/ideas/sources.py` 한 곳에 있다. 소스당 최신 10건.

| 소스 | 성격 | 수집 방식 | 반응 뱃지 |
|---|---|---|---|
| 어미새 `/os` | 패션 할인 | httpx | 좋아요·댓글 |
| 아이즈매거진 | 협업·드랍 | **Playwright** | 조회수 |
| 하입비스트 | 신상·콜라보 | RSS | — |
| 에스콰이어 · GQ | 남성 스타일링 | httpx | — |
| 엘르 · 보그 | 여성·트렌드 | httpx | — |

- 아이즈매거진만 서버 HTML에 글이 없어(완전 클라이언트 렌더링) 브라우저가
  필요하다. 로컬 앱은 브라우저를 띄우지 않으므로 그 소스만 빠지고,
  배치에서는 함께 수집된다.
- 반응 뱃지(🔥)는 소스별 임계값으로 판정한다. 스케일이 달라(어미새
  좋아요 3~10, 아이즈 조회 4천~1.7만) 공통 기준은 뜻이 없다.
- 무신사 매거진·에펨코리아·딜바다는 robots.txt가 차단해 넣지 않는다.

## 새 PC에서 시작하기

```bash
git clone https://github.com/hanwool-choi/willy-content-engine.git
cd willy-content-engine
```

1. **Python 3.11+** 설치 (Windows: `winget install --id Python.Python.3.12`)
2. **가상환경** — OneDrive·Dropbox 같은 동기화 폴더 **밖에** 만든다.
   동기화 폴더 안에 두면 수만 개 파일이 계속 동기화돼 느려지고 깨진다.
   ```powershell
   python -m venv C:\venvs\willy
   C:\venvs\willy\Scripts\python.exe -m pip install -e ".[dev]"
   C:\venvs\willy\Scripts\python.exe -m playwright install chromium
   ```
3. **키 넣기** — `.env.example`을 `.env`로 복사하고 값을 채운다.
   `.env`는 저장소에 없으므로(공개 저장소라 의도적으로 제외) **기존 PC의
   `.env`를 옮기거나 키를 새로 발급**해야 한다.
4. **실행** — `C:\venvs\willy\Scripts\python.exe run.py` → http://127.0.0.1:8765

TLS 검사 프록시가 있는 사내망에서도 그대로 동작한다 (진입점에서 `truststore`로
OS 인증서를 신뢰하게 해둠). 이게 없으면 모든 외부 호출이 인증서 오류로 죽는다.

자동 게시 워크플로는 `.env`가 아니라 **GitHub Actions Secrets**에서 같은
이름의 값을 읽는다 (환경변수가 `.env`보다 우선). 키 항목:

- `KMA_SERVICE_KEY` — 공공데이터포털 기상청 단기예보/중기예보 서비스 키 (선택)
- `ANTHROPIC_API_KEY` — 룩 분석용 Claude API 키
- `GEMINI_API_KEY` — 룩 분석용 Gemini API 키 (Claude 키가 없을 때 사용)

룩 분석은 두 키 중 있는 쪽을 쓴다 (둘 다 있으면 Claude). Gemini는
https://aistudio.google.com 에서 카드 등록 없이 무료 티어 키를 만들 수 있고,
하루치 분석(비전 12회)은 무료 한도 안에 넉넉히 들어간다.

`KMA_SERVICE_KEY`가 비어 있으면 날씨는 자동으로 Open-Meteo로 대체된다. 키 등록
없이 바로 실행 가능하다. 기상청은 국내 지역 조건 정확도가 더 높고, Open-Meteo는
등록 없이 즉시 쓸 수 있다는 트레이드오프가 있다.


## 키 없이 먼저 둘러보기

```bash
python demo.py
```

http://127.0.0.1:8770 에서 열린다. 분석만 가짜로 대체하고, 날씨는 실제
Open-Meteo를 호출하며 룩 사진도 첫 실행 때 실제 수집기로 받아와
`.demo_cache/`에 캐싱한다. 배정·경고·조건부 추천은 실제 코드 그대로다.

캐시된 사진은 제3자 저작물이라 `.demo_cache/`는 저장소에 올리지 않는다.
사진을 다시 받고 싶으면 그 폴더를 지우고 다시 실행하면 된다.

## 실행 (로컬 앱)

```bash
python run.py
```

브라우저에서 http://127.0.0.1:8765 접속. 화면 흐름은 두 단계다:

1. **룩 수집 · 분석** (2~4분) — 끝나면 보드와 수집 룩이 채워진다.
   썸네일을 클릭하면 확대 보기에서 이미지를 받거나 원본 페이지로 갈 수 있다.
   마음에 안 들면 **이미지 재수집**으로 겹치지 않는 새 사진을 다시 걷는다.
2. **텍스트 콘텐츠 생성** — 채널 말투 기반 3가지 톤. 카드마다 복사 버튼.

말투 기준 예시글은 `src/willy/texter.py`의 `STYLE_EXAMPLE`에 있다. 채널
톤이 달라지면 이 값만 최신 게시글로 바꾸면 된다.

## 매일 아침 자동 게시 (GitHub Actions + Pages)

`.github/workflows/daily.yml` 이 **매일 07:40 KST**(22:40 UTC)에 수집·분석·
텍스트 생성을 돌리고, 결과를 정적 보드로 만들어 GitHub Pages에 올린다.
PC를 켜둘 필요가 없고 주소가 고정된다.

정시(:00)에 걸지 않는 이유가 있다. 예약 작업이 정시에 몰리면 GitHub이
실행을 미루거나 건너뛴다 — 08:00 KST로 걸었을 때 트리거가 아예 오지
않은 적이 있다. 아침에 보드가 비어 있으면 Actions 탭에서 **Run workflow**로
바로 돌리면 된다.

```bash
python build_site.py site   # 로컬에서 같은 결과를 만들어 볼 때
```

준비 (저장소 설정에서 한 번만):

1. **Settings → Pages → Source: GitHub Actions** 로 지정
2. **Settings → Secrets and variables → Actions** 에 `GEMINI_API_KEY`,
   `KMA_SERVICE_KEY` 등록 (환경변수가 `.env`보다 우선한다)
3. 무료 플랜에서 Pages는 **공개 저장소**만 지원한다. 공개로 돌리기 전에
   `.env`에서 키를 비우고 재발급할 것 — 공개 저장소의 키는 봇이 즉시 긁어간다

수동 실행은 Actions 탭 → 워크플로 선택 → Run workflow.

게시되는 페이지는 사진을 재업로드하지 않고 **각 출처의 원본 주소를 그대로
표시**한다(핫링크). 제3자 저작물을 저장소에 담지 않기 위해서다.

링크를 공유할 때 뜨는 미리보기 이미지는 `assets/og.png`다. 교체하려면 같은
이름으로 덮어쓰면 된다 (자세한 규격은 `assets/README.md`).

## 외부 공유 (선택)

서버가 뜬 상태에서 별도 터미널에서:

```powershell
.\share.ps1
```

Cloudflare 무료 임시 터널로 `https://????.trycloudflare.com` 공개 주소가
나온다. 창이 열려 있는 동안 외부 사용자가 같은 화면을 쓸 수 있다.

- URL은 실행할 때마다 바뀐다 (고정 주소는 Cloudflare 계정 필요)
- 인증이 없으므로 신뢰하는 사람에게만 공유할 것 — URL을 아는 누구나
  수집을 실행해 무료 API 한도를 쓸 수 있다
- 상태는 하나를 같이 본다 (누가 수집하든 모두 같은 보드가 보인다)

## 최펄럭 채널 — 즐겨찾기 기반 코스 브리핑 (별도 흐름)

두 번째 스레드 채널(`파워J 가이드 최펄럭`)용 도구다. 위의 패션 파이프라인과는
독립적으로 돈다. 네이버 지도 즐겨찾기 공유 폴더 3개(카페·식당·스팟)를 읽어
코스 슬롯에 배정하고, 게시물 초안까지 뽑는다.

**코스에는 즐겨찾기에 있는 장소만 들어간다.** 채널의 신뢰 기반이
"큐레이터가 실제 저장해둔 곳"이라서, 코드가 후보를 지어내지 않는다.

```bash
python tools/pulluk_course.py --list                  # 등록된 지역
python tools/pulluk_course.py --region paju           # 코스 초안 출력
python tools/pulluk_course.py --region ganghwa --refresh --out drafts/ganghwa.md
python tools/pulluk_favorites.py --addr 성수          # 즐겨찾기 목록만 훑기
python tools/pulluk_search.py 순대국 --folder 식당    # 메뉴로 모아보기
```

동작:

1. 즐겨찾기 수집 → `.cache/pulluk_favorites.json`에 캐시. 두 번째 실행부터는
   캐시로 돌아 네트워크가 막힌 자리에서도 초안이 나온다 (`--refresh`로 재수집)
2. 지역 필터 — 주소 키워드 **또는** 중심 반경. 근교는 주소 표기가 제각각이라
   둘 중 하나만 걸려도 후보로 본다
3. 슬롯 배정 — 점심 / 실내 문화 앵커 / 대형 카페 / 실내 쇼핑 / 저녁.
   공원·수목원 같은 야외 분류는 실내 코스에서 자동으로 빠진다
4. 동선 — 되돌아가는 구간에 벌점을 매겨(`BACKTRACK_WEIGHT`) 한 방향으로
   꿰이는 조합을 고른다. 채널 원칙이라 정렬이 아니라 비용 함수로 강제한다
5. 출력 — 본문 초안(확정 말투 템플릿) + 답글1(주소·지도링크) + 답글2(투어지 접수)
   + 답사 작업표

한 줄 코멘트와 실전 팁은 `___`로 비워 둔다. 즐겨찾기가 주지 않는 정보라
지어내지 않는다. 후보가 없는 슬롯도 숨기지 않고 빈 칸으로 드러낸다.

지역을 늘리려면 `src/willy/pulluk/regions.py`의 `REGIONS`에 한 줄 추가한다.

### 메뉴로 모아보기

코스가 아니라 "순대국집만" 같은 저장형 리스트를 뽑을 때는 `pulluk_search.py`를 쓴다.

```bash
python tools/pulluk_search.py 순대국 --folder 식당     # 식당 폴더에서만
python tools/pulluk_search.py 순대국 --area            # 지역별로 묶어서
```

상호뿐 아니라 **네이버 분류까지 같이 본다**. 분류만 `순댓국`이고 상호에는 메뉴가
없는 집(`역전회관` 같은)을 상호만 보면 놓치기 때문이다.

한글 부분문자열 검색은 사이시옷에서 샌다 — **`순댓국`에는 `순대`가 들어 있지 않다**
(순/댓/국). 표기 변형은 `search.py`의 `TERM_ALIASES`가 펼쳐 준다. 새 메뉴에서
같은 문제가 생기면 거기에 한 줄 추가하면 된다.

## 테스트

```bash
pytest
```

테스트는 네트워크를 타지 않는다. 외부 응답은 페이크/고정 픽스처로 대체한다.

## 주의

- 수집 사진은 **제3자 저작물**이다. 게시 페이지는 사진을 재업로드하지 않고
  각 출처의 원본 주소로 표시(핫링크)하며, 저장소에도 담지 않는다
  (`.workspace/`, `.demo_cache/` 는 추적 제외).
- 이미지 저장은 CDN이 CORS를 허용한 곳(유니클로)만 곧바로 받아진다.
  무신사·WEAR는 새 탭으로 열리고 거기서 직접 저장해야 한다.
- 공공데이터포털 키는 **디코딩된 값**을 넣어야 한다. `%2B` 같은 인코딩
  값을 넣으면 이중 인코딩으로 인증에 실패한다.
- 저장소가 공개다. `.env`를 다시 추적에 넣지 말 것 (테스트가 막고 있다).

## 미확정 항목

이미지·영상 생성은 사용자가 별도 엔진에서 수동으로 진행한다. 자동화하려면
`src/willy/generator/`에 `ImageGenerator` 구현체를 붙이고 컨셉 프리셋
(`presets/concept_v1.yaml`의 `render.*`, `model.*.face_ref`)을 채우면 된다.
현재 `NoopGenerator`는 원본을 복사하고 프롬프트만 남긴다.

## 설계 문서

- 초기 스펙: `docs/superpowers/specs/2026-07-31-tomorrow-outfit-pipeline-design.md`
- 초기 구현 계획: `docs/superpowers/plans/2026-07-31-tomorrow-outfit-pipeline.md`
- 경량화 설계: `docs/superpowers/specs/2026-08-03-lightweight-pipeline-design.md`
- 최펄럭 채널 설계: `docs/superpowers/specs/2026-08-07-pulluk-channel-design.md`
- 실내 드라이브 코스 기획: `docs/superpowers/specs/2026-08-08-pulluk-indoor-drive-course-plan.md`

초기 문서는 주간 14칸·2단계 컨펌 시절 기준이라 현재 흐름과 다르다.
현재 동작은 이 README와 테스트(`tests/`, 233개)가 기준이다.
