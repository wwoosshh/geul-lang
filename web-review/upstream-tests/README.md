# 원본 앱 통합 실행 대조

`excalidraw-scroll.test.tsx`는 원본 Excalidraw의 테스트 도우미와 앱을 그대로 사용한다. 선택 구간의 helper·부모 컴포넌트를 대역으로 교체하지 않는다. 원본 Vitest/jsdom 환경에 있는 canvas·font·storage·throttle 대역과 레이아웃 제약은 유지한다. DOM에 버튼이 있다는 결과는 CSS 표시·가림 검증과 구분한다.

## 색상 입력의 별도 원본 실행

`excalidraw-color.test.tsx`는 색상 입력 변경의 원본 전후 앱을 실행한다. 기존 복귀 버튼 작업 사본과 분리한 `build/runtime-apps/excalidraw-color-786ab266`을 사용한다. 저장소 루트에서 다음과 같이 준비한다.

```powershell
git -c safe.directory=C:/geul/geul-lang/build/research/excalidraw -c core.longpaths=true worktree add --detach C:/geul/geul-lang/build/runtime-apps/excalidraw-color-786ab266 786ab266ff3a9cfffaed16804cf9132b44bc08ae
Set-Location build/runtime-apps/excalidraw-color-786ab266
corepack.cmd yarn install --frozen-lockfile --ignore-scripts --non-interactive
Set-Location ../../../web-review
npm.cmd run test:upstream-color
```

원본 커밋은 `69d4c346cc82ee5f64b6fa6bb91ad94422fedfb3` → `786ab266ff3a9cfffaed16804cf9132b44bc08ae`다. 삭제·추가된 테스트 파일을 포함한 변경 파일 다섯 개와 원본 tree·환경·색상 판별 함수·실험 코드·입력 예시 해시를 기록한다. 다른 작업 사본의 node_modules를 공유하지 않는다. 브라우저 검증 서버 56680을 중지한 뒤 전후 실행기를 사용한다.

`corpus/color-scenarios.json`의 9개 경로와 예상 결과는 수동으로 지정했다. 원본 앱을 전후 각각 9회 열고 메뉴·색상 선택기를 클릭한 뒤 testing-library change/blur 이벤트를 보낸다. 100개 관찰과 전후 대응 50개 상태에서 입력창 문자열·저장된 배경색·ARIA 속성 존재와 값·오류 문구·role·클래스를 확인했다. 입력 문자열 차이 4개, 오류 안내가 생긴 상태 12개, 저장 색 차이 0개다. 같은 경로의 연속 단계이며 독립적인 변경 50건을 뜻하지 않는다.

같은 유효 색을 공백과 함께 다시 입력하면 저장 색이 같아도 표시가 달라지는 경로를 확인했다. 지우는 중간에 유효한 4자리·3자리 색을 통과하면 그 값이 저장되며, 빈 입력에서 blur하면 마지막 3자리 색이 다시 표시된다. 후 버전의 원본 colorInput 테스트 30개도 별도 최초 실행에서 통과했다. 전체 검증의 집계에는 새 고정 경로 테스트 18개만 사용한다.

기존 `aria-invalid` IR은 시나리오에서 선언한 예상 메시지를 입력받아 DOM 속성과 조건부로 대조한다. 관찰한 오류 DOM을 모델 입력으로 되돌리지 않는다. 이 실행은 hooks·이벤트의 글 해석기를 추가한 것이 아니다. 원본 jsdom 대역과 원본 테스트처럼 비워 둔 ResizeObserver를 사용하며 픽셀 표시·보조 기술·임의 스케줄을 보증하지 않는다. 실제 배경색은 원본 `window.h` 시험 접근자로 읽는다.

결과는 `build/web-review/upstream-color-results.json`과 그 안에 연결된 새 실행 폴더의 `comparison.md`·`paired.json`·원본 증거·로그에 남는다. 기존 JSX 조각 실험의 `originalComponentExecutions: 0`은 그 실험 자체의 범위를 유지하며, 별도 통합 실행의 18회 앱 mount와 합쳐 덮어쓰지 않는다. 전체 행동 **0/12**, 사람 참가자 **0명**이다.

### 색상 입력의 실제 브라우저 기록

`color-browser.html`·`color-browser.tsx`·`color-browser.config.mts`를 색상 작업 사본의 `geul-color-browser.*`로 복사하고 `node node_modules/vite/bin/vite.js --config geul-color-browser.config.mts`로 56680에 실행했다. 원본 workspace alias·앱·React·CSS를 사용하며 test setup·대역을 가져오지 않는다. 원본 `onChange`가 호스트에 전달한 배경색을 보이는 output에 기록하고 CUA가 그 DOM을 읽었다. 원본 컴포넌트 내부 hook 상태를 읽지 않는다.

1280 × 1000 브라우저의 798 × 648 앱에서 전후 각 18단계, 총 36개 관찰을 기록했다. 메뉴·선택기는 실제 클릭으로 열고, fill과 여섯 Backspace·세 Tab을 각 버전에서 실행했다. fill은 개별 문자 입력을 대신하는 증거가 아니다. 입력 표시 차이 4개, 오류 안내 추가 6개, Tab으로 입력을 마친 결과 6개를 확인했다. 오류 문구 크기·색상·테두리와 초점도 기록했지만 보조 기술의 음성 안내는 검사하지 않았다.

원본 기록은 `evaluation/browser-evidence/2026-09-09-color.json`과 `.lock.json`에 고정했다. `npm.cmd run check:color-browser-recording`은 이 기록·원본·화면 자산을 재대조하며 브라우저를 다시 실행하지 않는다. `build/web-review/color-browser-comparison.md`에 비교표를 생성한다. CUA 보조 함수의 버전 라벨이 전 버전에서도 after로 남은 메타데이터 문제는 원시 `capturedLabel`에 보존했다. 실제 화면에서 읽은 원본 commit을 검증하여 전후를 구분하며 이 라벨을 버전 근거로 사용하지 않는다. 파일의 해시는 외부 관찰 인증을 대신하지 않는다.

## 실행 준비

기본 원본 캐시 `build/research/excalidraw`와 corpus 잠금 파일을 먼저 준비한다. 다음 명령은 저장소 루트에서 실행한다. 기존 작업 사본을 덮어쓰지 않는다.

```powershell
git -c safe.directory=C:/geul/geul-lang/build/research/excalidraw -c core.longpaths=true worktree add --detach C:/geul/geul-lang/build/runtime-apps/excalidraw-scroll-a1d9b16 a1d9b16b0dc485566cfc90ece8269443f8726d63
Set-Location build/runtime-apps/excalidraw-scroll-a1d9b16
corepack.cmd yarn install --frozen-lockfile --ignore-scripts --non-interactive
Set-Location ../../../web-review
npm.cmd run test:upstream
```

마지막 경로 이동은 작업 사본에서 저장소 루트의 `web-review`로 이동한다. 원본 packageManager는 Yarn 1.22.22이고 잠금 파일은 두 커밋에서 동일하다. 설치 스크립트는 실행하지 않는다. 설치된 의존성 파일 전체의 독립 해시 검증까지 수행한 것은 아니다.

실행기는 전용 detached worktree가 지정한 원본 저장소에 속하는지, 추적 파일에 변경이 없는지, 커밋이 지정한 전후 중 하나인지 확인한다. 전후 커밋을 순서대로 checkout하며 완료 또는 실패 시 원래 커밋으로 돌린다. 기존 테스트 사본의 내용이 다르면 덮어쓰지 않는다. 각 실행은 새 디렉터리에 로그·Vitest 결과·관찰 입력·분석 IR·모델 대조를 남긴다. 실패 실험도 남겨 둔다.

## 관찰 범위

- 모바일 구성, 보기 모드 여부, 기본 UI·복귀 UI만 활성·전체 비활성·해당 UI 생략의 8개 시나리오를 전후 실행한다.
- 원본 wheel 처리기로 콘텐츠 밖으로 이동한다. 버튼이 생기면 클릭하고 `scrolledOutside`가 거짓이 되는지 확인한다.
- 메뉴·사이드바는 테스트 API로 연 상태를 명시한다. 이 상태의 사용자 조작을 통한 도달 가능성은 증명하지 않는다.
- 실제 AppState와 원본 UI 활성 판정에서 입력을 추출한다. `MobileMenu`의 객체 전달 모델과 DOM 버튼 개수를 대조한다.
- 변경한 TSX 두 파일뿐 아니라 CSS를 포함한 **원본 변경 세 파일**과 전체 커밋 tree를 결합한다. 기존 12개 사례의 분모는 유지한다.

jsdom은 브라우저처럼 레이아웃·ResizeObserver 갱신을 구동하지 않고, 원본 앱의 창 resize 이벤트는 편집 모드에서만 구독된다. 처음 창 resize 이벤트만 보낸 실험에서는 보기 모드 4개 시나리오가 desktop으로 남아 실패했다. 원본 `withExcalidrawDimensions` 도우미와 같은 방식으로 원본 `refreshEditorInterface()`·`refresh()`를 호출해 환경을 준비했다. `formFactor`·`scrolledOutside`를 원하는 값으로 직접 대입하지 않는다. 이 준비는 실제 브라우저의 ResizeObserver를 시험한 것이 아니다.

첫 고정 실행은 16개 테스트, 102개 상태 대조, 6개 복귀 클릭을 통과했다. 대응하는 전후 관찰 50개 중 버튼 수 변화는 6개이며, 같은 시나리오의 서로 다른 단계가 포함돼 독립 변경 6건을 뜻하지 않는다. 전체 행동 검증 **0/12**, 사람 참가자 **0명**이다.

결과는 `build/web-review/upstream-results.json`에 최신 성공 실행 경로가 기록되고, 해당 `upstream/run-*/report.json`에 원본·시험 코드·실행기 해시와 제한이 남는다. 보고서의 `runnerSha256`·`fixtureSha256`가 현재 코드와 다른 경우 현재 구현의 실행 증거로 재사용하지 않는다.

## 실제 브라우저 기록

`browser.html`·`browser.tsx`·`browser.config.mts`는 같은 작업 사본 루트의 `geul-browser.html`·`geul-browser.tsx`·`geul-browser.config.mts`로 복사해 실행했다. `node node_modules/vite/bin/vite.js --config geul-browser.config.mts`로 localhost:56678에 열고 `/geul-browser.html`을 CUA 브라우저에서 검사했다. 원본 소스 alias와 React 플러그인을 사용한 개발 실행이며 프로덕션 앱 전체 진입점과 구분한다. 서버를 중지한 뒤 커밋을 바꾸고 재시작·새로고침해야 한다. 실행 중인 서버가 있는 작업 사본에서 통합 시험의 checkout을 함께 진행하지 않는다.

1280 × 1000 브라우저 안의 390 × 650 앱에서 전후 각 6개 조건을 실행했다. 호스트 API로 스크롤 위치를 콘텐츠 밖으로 바꾸고, 원본 버튼의 브라우저 클릭 6회와 클릭 전후 총 18개 관찰을 보존했다. 버튼 중앙의 가림 여부·사각형·계산 스타일도 읽었다. 별도 helper·jsdom 대역은 사용하지 않았다. 이 호스트 API 시작 조건은 실제 사용자 제스처를 통한 도달 증명이 아니다.

관찰 데이터는 `evaluation/browser-evidence/2026-09-09-scroll.json`이고 원본 tree·CSS·잠금 파일·검증 화면 해시는 옆의 `.lock.json`에 고정했다. `npm.cmd run check:browser-recording`은 이 **기록을 현재 모델과 재대조**한다. 브라우저를 다시 실행하는 명령이 아니다. 기록은 CUA 출력에서 옮긴 실험 증거이며 해시가 외부 인증을 대신하지 않는다.

보기 모드의 두 UI 조건에서 버튼이 생기는 변화 외에, 복귀 버튼만 켠 편집 모드에서 y가 659.5→739.5로 이동했다. 이 80px 배치 변화는 현재 객체 전달 모델의 관찰 범위 밖이다. 따라서 전체 행동 완료로 세지 않는다. 생성된 비교 표와 이 한계는 `build/web-review/browser-comparison.md`에서 확인한다.
