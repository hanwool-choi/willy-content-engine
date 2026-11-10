---
name: willy-threads-planner
description: 최윌리 옷장연구소(Threads @choi.willy.lab) 채널의 전체 게시글·반응·말투를 Aside 브라우저(u0 계정)로 수집·분석하고, 그 근거로 신규 콘텐츠(특히 '[평생 재구매할 족보]' 시리즈)를 기획해 제품 이미지까지 붙여 Threads 임시저장본으로 넣는 스킬. "옷장연구소", "최윌리", "스레드 콘텐츠 기획", "족보 기획", "족보 여자편/남자편/○○편", "반응 좋았던 글 분석", "임시저장에 넣어줘" 같은 요청에 사용.
---

# 최윌리 옷장연구소 Threads 콘텐츠 기획

채널 분석부터 기획, 제품 소싱, 이미지 첨부, **임시저장**까지 한 흐름으로 진행한다.
게시는 하지 않는다. 사용자가 임시저장본을 직접 검토하고 올린다.

- 도구: `scripts/willy.py`. 모든 조작은 `aside repl --account u0`로 실행한다. Aside 앱이 켜져 있어야 한다.
- 기준 분석: `references/channel-analysis.md`. 기획 전에 반드시 읽는다.
- 작업 폴더: 회차마다 새 폴더를 만든다. 예: `cowork\옷장연구소\<YYMMDD>_<주제>\`.

## 0. 사전 확인
```bash
aside --version          # 없으면 aside-browser 스킬로 설치/업데이트
aside account list       # u0 = 채널 계정(Threads 로그인됨)
```
Aside 브라우저를 다룰 때는 aside-browser 스킬의 규칙을 따른다(`aside guide`, `aside guide repl`).

## 1. 채널 데이터 갱신 (분석 파일이 2주 넘었거나 사용자가 요청할 때)
```bash
python ~/.claude/skills/willy-threads-planner/scripts/willy.py scrape --out posts.json   # 3~5분, 끝까지 자동 반복
python ~/.claude/skills/willy-threads-planner/scripts/willy.py analyze posts.json --top 20
```
- 결과가 기존 분석과 크게 다르면 `references/channel-analysis.md`의 숫자와 관찰을 갱신한다(날짜 명시).
- 기획의 기반이 되는 원본 히트 글이 있으면 댓글도 확인한다. 여기서 수요 신호와 반복 질문이 나온다.
  ```bash
  python .../willy.py replies https://www.threads.com/@choi.willy.lab/post/<id> --out replies.json
  ```

## 2. 기획
1. 근거 잡기: 어떤 히트 글의 확장인지(편/버전), 어떤 댓글 수요에 답하는지 한 줄로 적는다.
2. 아이템 선정 원칙:
   - 6~8개. 원본 글과 같은 카테고리 축을 유지한다(예: 초겨울편 = 장갑·머플러·비니·발열내의·부츠·향수).
   - '범용적으로 먹히는' 기준: 국내에서 쉽게 살 수 있고(공식몰·무신사·29CM), 현재 재고가 있고, 성별·체형을 덜 타는 스테디셀러.
   - 가격대: 기본은 2~15만 원대. 근본템 1~2개는 25만 원대까지 허용한다. 한 줄 안에 '가성비 → 근본' 화살표로 두 단계를 넣을 수 있다.
   - 협찬·제휴 링크는 본문에 넣지 않는다. 제휴링크 글은 반응이 0에 가깝다.
   - 원본 글과 같은 제품을 반복하지 않는다. 단, 댓글에서 나온 질문(예: 터치 장갑)은 반영한다.
3. 제품 확인: Aside 에이전트에게 위임한다.
   ```bash
   aside exec --account u0 --json --timeout 9m "<카테고리별 후보> 각각의 공식 판매처 상품 URL, 현재 판매가, 대표 이미지 원본 URL(흰 배경 누끼 우선)을 조사해 JSON 배열 [{category, product, brand, price_krw, page_url, image_url, note}]로만 답해. 품절·단종이면 대체안."
   ```
   결과를 `products.json`으로 저장한다. 이미지를 내려받아 **눈으로 확인**한다. 모델 착용컷, 텍스트가 박힌 배너, 다른 색상이면 교체한다.
4. 본문 작성: `references/channel-analysis.md` §3 톤앤매너와 §4 포맷을 따른다. **§5 운영자 편집 패턴을 가장 우선한다.**
   - 지난 임시저장본이 게시됐다면 게시본과 초안을 비교해서 §5에 누적한 뒤 쓴다.
   - 게시되면 임시저장 목록에서 빠진다. 숫자가 줄었다면 프로필 최신 글을 먼저 확인한다.
   - 지켜야 할 것: 반말 단정형에 '함니다/슴니다' 섞기, `※ 업체에 어떠한 대가도 받지 않음.`, `카테고리 : 브랜드 제품명` 줄, 댓글 추천 CTA와 팔로우 CTA.
   - **경험 사실을 지어내지 않는다.** "3개째 재구매", "여사친 검수" 같은 개인 경험 문장은 사용자가 확인해 준 경우에만 쓴다. 근거 없는 효능이나 수치도 쓰지 않는다.
   - Threads 한도는 500자다. 보통 300~400자에서 끝낸다.
   - `post.txt`로 저장한다.

## 3. 임시저장
```bash
python .../willy.py draft post.txt products.json --dry-run   # 흐름 검증(마지막에 '저장 안 함'으로 버림)
python .../willy.py draft post.txt products.json             # 실제 임시저장
```
- 이미지는 products.json 순서 = 본문 번호 순서로 첨부된다. REPL 안에서 fetch하므로 로컬 파일은 필요 없다.
- 출력의 `imgs`와 `expectedImgs`가 같은지 확인한다. 저장 후 프로필 우측 '임시 저장본' 숫자가 1 늘었는지도 확인한다. 페이지를 새로고침해야 반영된다.
- **'게시' 버튼은 절대 누르지 않는다.** 게시는 사용자가 결정한다.

## 4. 결과 보고
- 기획 근거(어떤 히트 글과 댓글에서 출발했는지), 아이템 표(카테고리·제품·가격·판매처 링크), 본문 전문, 임시저장 결과.
- 추천 게시 시각: 분석상 21~24시 또는 06~09시.
- 작업 폴더에 `post.txt`, `products.json`, 내려받은 이미지, `기획안.md`를 남긴다.

## 알려진 함정
- `aside repl`은 호출마다 새 세션이다. `openTab()`으로 연 탭은 종료 시 닫히고 `./artifacts`도 남지 않는다. 결과는 stdout의 `@@JSON@@`으로 받는다.
- 프로필 무한 스크롤은 중간에 멈춘다. scrape는 위아래로 흔들고 여러 회차를 이어 붙여 해결하며, 2회 연속 신규 0개면 끝으로 본다.
- REPL의 `getByRole`은 간헐적으로 실패한다. 버튼은 snapshot ref로 누른다.
- '임시 저장하시겠어요?' 확인창은 접근성 트리에 잡히지 않는다. 보이는 DOM 텍스트로 클릭한다.
- 작성창이 겹쳐 열리면(인라인 입력창 클릭 + '새로운 스레드') 2개가 된다. draft는 작성창이 정확히 1개가 아니면 중단한다.
- 반응 지표: 아이콘 라벨이 `aria-label`이 아니라 `<svg><title>`에 있다.
