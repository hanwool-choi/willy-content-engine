"""최윌리 옷장연구소(@choi.willy.lab) Threads 채널 도구 — Aside 브라우저(u0 계정) 경유.

서브커맨드
  scrape   [--out posts.json]            프로필 '스레드' 탭 전체 게시글 + 반응 수집
  analyze  posts.json [--top 30]         유형별·시간대별 반응, 상위 게시글, 말투 어미 통계
  replies  <post_url> [--out r.json]     특정 게시글 댓글(+이미지 URL) 수집
  draft    post.txt images.json [--dry-run]
           본문 입력 + 이미지 첨부 후 '임시 저장'. 게시 버튼은 절대 누르지 않음.
           --dry-run 이면 마지막에 '저장 안 함'으로 버려서 흐름만 검증.

모든 브라우저 조작은 `aside repl --account u0 --file <js>`로 실행한다.
REPL 세션은 매 호출마다 새로 뜨고 openTab()으로 연 탭은 종료 시 닫히므로,
한 작업(수집·임시저장)은 한 스크립트 안에서 끝낸다. 결과는 stdout의 @@JSON@@ 뒤에 싣는다.
"""
import argparse, json, os, re, statistics as st, subprocess, sys, tempfile, collections

HANDLE = "choi.willy.lab"
PROFILE = f"https://www.threads.com/@{HANDLE}"
ACCOUNT = os.environ.get("WILLY_ASIDE_ACCOUNT", "u0")

sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")


def run_js(js: str, timeout=170):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        p = subprocess.run(["aside", "repl", "--account", ACCOUNT, "--file", path],
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    finally:
        os.unlink(path)
    out = p.stdout + p.stderr
    if "@@JSON@@" not in out:
        raise SystemExit(f"aside repl 실패:\n{out[-2000:]}")
    return json.JSONDecoder().raw_decode(out.split("@@JSON@@", 1)[1])[0]


# 기존 Threads 탭이 있으면 붙고, 없으면 새로 연다(새 탭은 스크립트 종료 시 닫힘).
ATTACH = f"""
const tabsW = await listBrowserTabs();
const hitW = tabsW.find(t => (t.url||'').includes('threads.com'));
if (hitW) {{ await attachBrowserTab(hitW.targetId); await page.goto('{PROFILE}'); }}
else {{ await openTab('{PROFILE}'); }}
await sleep(3000);
"""

GRAB = r"""
const grabW = async () => page.evaluate((handle) => {
  const out = [];
  document.querySelectorAll('div[data-pressable-container="true"]').forEach(c => {
    const tl = c.querySelector('a[href*="/post/"] time'); if (!tl) return;
    const href = tl.closest('a').getAttribute('href');
    if (!href.startsWith('/@' + handle + '/')) return;
    const m = {};
    c.querySelectorAll('svg').forEach(s => {
      const lab = s.getAttribute('aria-label') || s.querySelector('title')?.textContent || '';
      const k = lab.startsWith('좋아요') ? 'like' : lab === '답글' ? 'reply' : lab === '리포스트' ? 'repost' : lab === '공유하기' ? 'share' : null;
      if (!k || k in m) return;
      const el = s.closest('[role=button]') || s.parentElement.parentElement;
      m[k] = (el?.innerText || '').trim();
    });
    const imgs = [...c.querySelectorAll('img')].filter(i => (i.alt||'').startsWith('Photo')).map(i => i.src);
    out.push({href, dt: tl.getAttribute('datetime'), m, text: c.innerText, imgs});
  });
  return out;
}, '%s');
""" % HANDLE


def cmd_scrape(a):
    # 프로필은 가상 스크롤이라 위에서부터 한 번에 내려가며 모아야 한다. 120s 제한 때문에 2~3회 이어서 실행.
    loop = r"""
const colW = {}; let stW=0, lW=0; const tW=Date.now();
for (let i=0;i<150 && stW<14 && Date.now()-tW<100000;i++){
  for (const p of await grabW()) if (!colW[p.href] || colW[p.href].text.length < p.text.length) colW[p.href]=p;
  const n=Object.keys(colW).length; if(n===lW) stW++; else stW=0; lW=n;
  if (stW>0 && stW%4===0) { await page.mouse.wheel(0,-3000); await sleep(1500); }  // 로딩 멈춤 시 흔들어 깨우기
  await page.mouse.wheel(0,3500); await sleep(900);
}
console.log('@@JSON@@'+JSON.stringify({posts:Object.values(colW)}));
"""
    first = run_js(ATTACH + GRAB + loop)
    allp = {p["href"]: p for p in first["posts"]}
    cont = f"const tabsC = await listBrowserTabs(); await attachBrowserTab(tabsC.find(t=>(t.url||'').includes('{HANDLE}')).targetId);\n"
    print(f"  1회차 {len(allp)}개", file=sys.stderr)
    zero = 0
    for rnd in range(2, 12):  # 새 글이 2회 연속 0개면 채널 끝으로 본다
        first = run_js(cont + GRAB + loop)
        new = sum(1 for p in first["posts"] if p["href"] not in allp)
        for p in first["posts"]:
            if p["href"] not in allp or len(p["text"]) > len(allp[p["href"]]["text"]):
                allp[p["href"]] = p
        print(f"  {rnd}회차 +{new} (누적 {len(allp)})", file=sys.stderr)
        zero = zero + 1 if new == 0 else 0
        if zero >= 2:
            break
    rows = [clean(p) for p in allp.values()]
    rows.sort(key=lambda r: r["dt"], reverse=True)
    json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(rows)}개 저장 → {a.out} (가장 오래된 글 {rows[-1]['dt'][:10] if rows else '-'})")


def num(s):
    s = (s or "").replace(",", "").strip()
    m = re.match(r"([\d.]+)\s*(천|만)?", s)
    return int(float(m.group(1)) * {"천": 1000, "만": 10000}.get(m.group(2), 1)) if m else 0


def clean(p):
    body = re.sub(r"^%s\n(패션\n)?[^\n]*\n" % re.escape(HANDLE), "", p["text"])
    body = re.split(r"\n번역하기\n", body)[0]
    body = re.sub(r"(\n[\d.,]+(천|만)?)+\s*$", "", body).strip()
    r = dict(href=p["href"], url="https://www.threads.com" + p["href"], dt=p["dt"], body=body,
             imgs=len(p["imgs"]), img_urls=p["imgs"], **{k: num(p["m"].get(k)) for k in ["like", "reply", "repost", "share"]})
    r["score"] = r["like"] + r["reply"] + 3 * r["repost"] + 2 * r["share"]
    return r


def typ(b):
    if "평생 재구매" in b or "족보" in b: return "족보/리스트"
    if "링크" in b and "수수료" in b: return "제휴링크"
    if any(k in b for k in ["세일", "할인", "직구", "엔저"]): return "세일·직구 정보"
    if re.search(r"[‘']", b) and len(b) > 80: return "단품 추천"
    if len(b) < 60: return "짧은 잡담/답글"
    return "기타"


def cmd_analyze(a):
    rows = json.load(open(a.posts, encoding="utf-8"))
    # 인용·리포스트 글은 원글 지표를 그대로 달고 나오므로 지표가 같은 글은 가장 이른 것만 남긴다.
    seen, uniq = set(), []
    for x in sorted(rows, key=lambda x: x["dt"]):
        k = (x["like"], x["repost"], x["share"], x["reply"])
        if x["like"] > 50 and k in seen: continue
        seen.add(k); uniq.append(x)
    print(f"# 게시글 {len(uniq)}개 (중복 지표 제거 전 {len(rows)}), 좋아요 중앙값 {st.median(x['like'] for x in uniq)}")
    g = collections.defaultdict(list)
    for x in uniq: g[typ(x["body"])].append(x)
    print("\n## 유형별")
    for k, v in sorted(g.items(), key=lambda kv: -st.mean(x["like"] for x in kv[1])):
        print(f"- {k}: {len(v)}개, 좋아요 평균 {round(st.mean(x['like'] for x in v))} / 중앙 {st.median(x['like'] for x in v)}, 공유 평균 {round(st.mean(x['share'] for x in v))}")
    h = collections.defaultdict(list)
    for x in uniq: h[((int(x["dt"][11:13]) + 9) % 24) // 3 * 3].append(x["like"])
    print("\n## 게시 시각(KST 3시간 단위): 글 수 / 좋아요 평균")
    for k, v in sorted(h.items()): print(f"- {k:02d}~{k+3:02d}시: {len(v)} / {round(st.mean(v))}")
    ends = collections.Counter()
    for x in uniq:
        for m in re.findall(r"(임니다|함니다|슴니다|음니다|했음|있음|됨|함|임)[.!\s]", x["body"] + " "): ends[m] += 1
    print("\n## 어미 빈도:", ", ".join(f"{k} {v}" for k, v in ends.most_common(9)))
    print(f"\n## 상위 {a.top} (점수 = 좋아요+답글+3×리포스트+2×공유)")
    for r in sorted(uniq, key=lambda r: -r["score"])[: a.top]:
        print(f"- {r['dt'][:10]} ♥{r['like']} 💬{r['reply']} 🔁{r['repost']} ↗{r['share']} 🖼{r['imgs']} | " + r["body"][:90].replace("\n", " / ") + f"  {r['url']}")


def cmd_replies(a):
    js = f"""
const pR = await openTab({json.dumps(a.url)}); await sleep(2500);
for (let i=0;i<15;i++){{ await pR.mouse.wheel(0,3000); await sleep(800); }}
const rR = await pR.evaluate(()=>{{
  const cs=[...document.querySelectorAll('div[data-pressable-container="true"]')];
  return {{ imgs:[...cs[0].querySelectorAll('img')].filter(i=>(i.alt||'').startsWith('Photo')).map(i=>i.src),
           replies: cs.slice(1).map(c=>c.innerText.slice(0,500)) }};
}});
console.log('@@JSON@@'+JSON.stringify(rR));
"""
    r = run_js(js)
    json.dump(r, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"댓글 {len(r['replies'])}개, 이미지 {len(r['imgs'])}장 → {a.out}")
    for t in r["replies"]: print("-", t.replace("\n", " | ")[:200])


def cmd_draft(a):
    text = open(a.post, encoding="utf-8").read().strip("\n")
    items = json.load(open(a.images, encoding="utf-8"))
    urls = [i["image_url"] if isinstance(i, dict) else i for i in items]
    final = "저장 안 함" if a.dry_run else "저장"
    js = ATTACH + f"""
const linesD = {json.dumps(text.split(chr(10)), ensure_ascii=False)};
const urlsD = {json.dumps(urls)};
// Aside REPL의 getByRole은 불안정 → snapshot ref로 클릭
const refD = async (label) => {{
  const sn = await snapshot(page, {{interactive:true}}); const key = 'button "' + label + '" [ref=';
  const out = sn.tree.split('\\n').filter(l => l.includes(key)).map(l => l.slice(l.indexOf(key) + key.length).split(']')[0]);
  if (!out.length) throw new Error('버튼 없음: ' + label); return out; }};
await page.locator((await refD('새로운 스레드'))[0]).click(); await sleep(1500);
if (await page.locator('[role="dialog"]').count() !== 1) throw new Error('작성창이 1개가 아님 — 열린 작성창부터 정리할 것');
const boxD = page.locator('[role="dialog"] [contenteditable="true"]').last();
await boxD.click();
for (let i=0;i<linesD.length;i++){{ await page.keyboard.insertText(linesD[i]); if(i<linesD.length-1) await page.keyboard.press('Enter'); }}
const filesD=[];
for (let i=0;i<urlsD.length;i++){{ const r=await fetch(urlsD[i]); if(!r.ok) throw new Error('이미지 '+(i+1)+' '+r.status);
  const ct=r.headers.get('content-type')||'image/jpeg'; filesD.push({{name:`item${{i+1}}.`+(ct.includes('png')?'png':'jpg'), mimeType:ct.split(';')[0], buffer:Buffer.from(await r.arrayBuffer())}}); }}
if (filesD.length) await page.locator('[role="dialog"] input[type="file"]').first().setInputFiles(filesD);
await sleep(4000 + 800*filesD.length);
const chkD = await page.evaluate(()=>{{const d=document.querySelector('[role="dialog"]'); return {{text:d.querySelector('[contenteditable="true"]').innerText, imgs:d.querySelectorAll('img[alt="이미지"]').length}};}});
await page.locator((await refD('취소'))[0]).click(); await sleep(1200);
// '임시 저장하시겠어요?' 확인창은 접근성 트리에 안 잡힘 → 보이는 DOM 텍스트로 클릭
const hitD = await page.evaluate((label)=>{{
  const els=[...document.querySelectorAll('div,span,button')].filter(e=>e.innerText && e.innerText.trim()===label && e.offsetParent!==null);
  const t = els.find(e=>e.getAttribute('role')==='button') || els[els.length-1]; if(!t) return false; t.click(); return true; }}, {json.dumps(final, ensure_ascii=False)});
if (!hitD) throw new Error('확인창 버튼 없음: ' + {json.dumps(final, ensure_ascii=False)});
// 저장은 이미지 업로드 때문에 수 초 걸린다 → 작성창이 닫힐 때까지 최대 15초 대기
let closedD = false;
for (let i=0;i<30;i++){{ await sleep(500); if (await page.locator('[role="dialog"]').count() === 0) {{ closedD = true; break; }} }}
if (!closedD) throw new Error('작성창이 15초 넘게 열려 있음 — 화면 확인 필요');
console.log('@@JSON@@'+JSON.stringify({{chars:chkD.text.length, imgs:chkD.imgs, expectedImgs:filesD.length, action:{json.dumps(final)}}}));
"""
    r = run_js(js)
    print(json.dumps(r, ensure_ascii=False))
    if r["imgs"] != r["expectedImgs"]:
        print("⚠ 첨부 이미지 수가 다름 — 임시 저장본을 열어 확인할 것", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scrape"); s.add_argument("--out", default="posts.json"); s.set_defaults(f=cmd_scrape)
    s = sp.add_parser("analyze"); s.add_argument("posts"); s.add_argument("--top", type=int, default=30); s.set_defaults(f=cmd_analyze)
    s = sp.add_parser("replies"); s.add_argument("url"); s.add_argument("--out", default="replies.json"); s.set_defaults(f=cmd_replies)
    s = sp.add_parser("draft"); s.add_argument("post"); s.add_argument("images"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_draft)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
