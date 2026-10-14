시세판 테스트는 도메인이나 유료 DB 없이 Python 3.10 이상과 SQLite로 실행합니다. 기존 홍보 페이지는 `index.html`에 유지하며 시세판은 개발 서버의 첫 화면 또는 정적 배포의 `test/`에서 제공합니다.

```bash
python3 -m market.server --host 127.0.0.1 --port 8787 --interval 600 --pages 3
```

서버는 시작할 때와 이후 600초마다 수집합니다. 바로템 판매 매물 최대 3페이지, 아이템베이 판매 매물 최대 3페이지와 완료 매물 1페이지를 수집합니다. 광고 배열은 제외하고 중복을 제거합니다. 전체 시장 평균이 아닌 표본 가격입니다. 아이템매니아는 미연동입니다.

`/api/prices`는 메모리에 보관한 가격을 읽으며 방문자 요청이 거래소 재조회를 일으키지 않습니다. `/api/health`는 갱신 횟수와 수집 상태를 제공합니다. 실패한 출처의 이전 값과 원래 수집 시각을 유지합니다. DB와 스냅샷은 Git에 포함하지 않는 `.market-data/`에 저장하고 관측 이력은 30일 보관합니다.

한 번 수집하거나 정적 배포 묶음을 만들 때는 다음 명령을 사용합니다.

```bash
python3 -m market.server --once
python3 scripts/build_market_demo.py
```

`dist/`는 시세판, 홍보 페이지와 실제 수집 스냅샷을 포함합니다. `.github/workflows/pages.yml`은 기존 첫 화면을 유지하고 새 시세판을 `test/`에 배포합니다. 공개 저장소의 표준 Linux Actions와 Pages를 사용하므로 이 테스트에 서버 임대료나 도메인 구매가 필요하지 않습니다. 이전 공개 스냅샷에서 가격·이력을 복원하며 장애 때 기존 가격을 유지합니다. 무의미한 빈 가격은 배포하지 않습니다.

예약 작업은 workflow가 기본 브랜치에 있을 때 작동합니다. `*/10 * * * *`는 10분 예약 목표이며 GitHub 대기·실행 지연으로 정확한 600초 갱신을 보장하지 않습니다. 장기간 저장소 활동이 없으면 예약 작업이 비활성화될 수도 있습니다. 안정적인 주기가 필요하면 Mac mini 또는 VM의 수집기를 사용합니다. 소스 HTML/JSON 접근 확인과 상업적 재게시 허가는 별개입니다.

맥미니를 보유하고 기존 인터넷을 사용하면 수집·SQLite를 맥에서 실행하고 방문자는 CDN에서 받을 수 있습니다. `deploy/worker.mjs`와 `deploy/wrangler.toml`은 Cloudflare의 무료 `workers.dev` 주소, 정적 자산과 KV 스냅샷을 위한 배포 구성을 제공합니다. 실제 계정 배포는 아직 수행하지 않았습니다.

```bash
python3 scripts/build_market_demo.py
npx wrangler@4 kv namespace create MARKET
# 출력된 namespace id를 deploy/wrangler.toml의 자리표시에 설정합니다.
npx wrangler@4 secret put MARKET_UPLOAD_TOKEN --config deploy/wrangler.toml
npx wrangler@4 deploy --config deploy/wrangler.toml
```

업로드 토큰은 명령의 보안 입력과 로컬 프로세스 환경으로 공급하며 Git·HTML·로그에 기록하지 않습니다. 발급된 주소의 `/internal/snapshot`을 `MARKET_UPLOAD_URL`로 설정하고 동일한 `MARKET_UPLOAD_TOKEN`을 수집 프로세스에 공급한 뒤 다음을 600초 간격으로 실행합니다.

```bash
python3 -m market.server --once
python3 scripts/push_snapshot.py --file .market-data/prices.json
```

맥이 잠자기·종료 상태면 수집은 멈추며 CDN은 마지막 가격을 표시합니다. 업로드 성공 전에는 무료 CDN 운영이 확인된 것으로 간주하지 않습니다. 사이트 전체를 10분마다 재배포하지 않고 JSON만 갱신하므로 Pages의 무료 월 500빌드 한도를 소진하지 않습니다. Worker 무료 일일 요청 한도와 KV 읽기·쓰기 한도는 사용량에 따라 확인해야 하며 넘으면 유료 Workers 최소 $5/월부터 검토합니다.

맥미니 도착 전에는 2GB VM $12/월과 주간 백업 20%로 $14.4/월부터 검토할 수 있습니다. 환율 1,400원/$·부가세 10% 가정은 약 22,176원/월, Workers $5를 추가해도 약 29,876원입니다. 개발·유지보수·데이터 사용료는 별도입니다. 맥미니 이후 추가 서버 임대료는 없앨 수 있으나 전기는 남습니다. 평균 5~20W를 가정하면 월 3.6~14.4kWh이며 단가 150~300원/kWh 가정은 약 540~4,320원입니다. Mac 실측 전력이나 실제 전기요금 견적은 아닙니다.

검증 명령:

```bash
python3 -m unittest discover -s market/tests -v
node tests/cloudflare-worker.test.mjs
node --check market.js
```

현재 클라우드 내부 캐시 API에서 동시 20개·총 500회 요청, 오류 0건, 약 394요청/초, p95 19.4ms를 관측했습니다. 맥미니·2GB VM 또는 외부 회선의 성능 보장은 아닙니다. 월 100만 PV는 평균 약 0.386페이지/초, 평균의 20배 피크는 약 7.72페이지/초지만 실제 사용 패턴·페이지당 API 호출·캐시 적중률을 따로 측정해야 합니다. 브라우저는 보이는 탭에서만 30초마다 캐시된 스냅샷을 확인하며 가격이 변하지 않으면 ETag 조건부 응답을 사용할 수 있습니다.
