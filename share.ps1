# 로컬 서버(127.0.0.1:8765)를 외부에서 접속할 수 있는 공개 URL로 묶는다.
#
#   .\share.ps1
#
# Cloudflare 무료 임시 터널(trycloudflare.com)을 쓴다 — 계정·설정 불필요.
# 실행하면 https://????.trycloudflare.com 주소가 출력되고, 이 창이 열려
# 있는 동안 외부 사용자가 그 주소로 접속할 수 있다.
#
# 주의:
# - URL은 실행할 때마다 바뀐다. 고정 주소가 필요하면 Cloudflare 계정으로
#   Named Tunnel을 만들어야 한다.
# - 인증이 없다. URL을 아는 사람은 누구나 수집을 실행해 무료 API 한도를
#   쓸 수 있으니, 신뢰하는 사람에게만 공유할 것.
# - run.py 서버가 먼저 떠 있어야 한다.

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    Write-Host "cloudflared가 없어 winget으로 설치합니다..."
    winget install --id Cloudflare.cloudflared --silent --accept-package-agreements --accept-source-agreements
    Write-Host "설치 완료. 새 터미널에서 다시 실행해 주세요 (PATH 반영)."
    exit
}

Write-Host "터널을 여는 중... 아래에 나오는 trycloudflare.com 주소를 공유하세요."
cloudflared tunnel --url http://127.0.0.1:8765
