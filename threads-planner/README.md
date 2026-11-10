# threads-planner

Threads `@choi.willy.lab` 채널 분석과 '[평생 재구매할 족보]' 콘텐츠 기획 도구입니다.
Aside 브라우저(u0 계정)로 다음을 처리합니다.

1. 전체 게시글 수집
2. 반응 분석
3. 댓글 수집
4. 제품 이미지를 붙여 Threads **임시저장**까지 진행(게시는 하지 않음)

- `skill/`: Claude Code 스킬 원본입니다. `~/.claude/skills/willy-threads-planner/`에 복사해서 씁니다.
  - `scripts/willy.py`: `scrape` / `analyze` / `replies` / `draft [--dry-run]`
  - `references/channel-analysis.md`: 채널 톤앤매너, 포맷, 반응 분석(2026-11-10 기준)
- `plans/`: 회차별 기획안(근거, 아이템 표, 본문, products.json).

제품 이미지와 다른 사용자의 댓글 원데이터는 저작권과 개인정보 문제로 이 공개 저장소에 올리지 않습니다.
로컬 작업 폴더(`cowork/옷장연구소/`)에만 보관합니다.
