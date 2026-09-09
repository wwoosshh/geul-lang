# 증거 색인

실행 숫자를 README에 누적하지 않는다. 아래 생성 결과와 각 실행의 로그를 근거로 확인한다. `verification-latest.json`은 마지막 성공한 실행이며 현재 소스와 엔진 해시가 같은지도 확인해야 한다.

| 확인할 것 | 근거 |
|---|---|
| 전체 검증과 각 단계 로그 | [마지막 성공 결과](../build/web-review/verification-latest.json), `build/web-review/verification/run-*/` |
| 실제 3개 프로젝트·12개 변경의 원본 고정 | [선정 사례](corpus/selection.json), [커밋·원본 해시](corpus/lock.json) |
| 변경 파일 전체 목록 | [변경 목록](../build/web-review/change-inventory.md) |
| 행동 표현 2건과 조건 대조 | [자료 색인](../build/web-behaviors/README.md), [자료·근거 해시](../build/web-behaviors/manifest.json) |
| 돌아가기 버튼의 조건·자식 전달 | [기존 흐름 대조](../build/web-review/flow-results.json) |
| 돌아가기의 부모·자식 결합과 원본 수정 자동 반영 | [결합 대조·세 합성 수정·원본 앱 관찰 재대조](../build/web-behaviors/excalidraw-scroll-back-view-mode/automatic-evidence.json), [변경 후 모델·생성 조건](../build/web-behaviors/excalidraw-scroll-back-view-mode/after-model.json) |
| 돌아가기 버튼의 React·원본 앱 실행 | [React 대조](../build/web-review/react-results.json), [원본 jsdom 결과](../build/web-review/upstream-results.json) |
| 돌아가기 버튼의 브라우저 관찰·배치 차이 | [관찰 설명](../build/web-review/browser-comparison.md), [보존 기록 대조](../build/web-review/browser-recording-results.json) |
| 모바일 필터의 거래 목록·예외 | [배열 선택 결과](../build/web-review/array-results.json), [원본 계측 기록](../build/web-review/array-trace-results.json) |
| 모바일 필터의 부모·자식 로딩 연결 | [속성 계산 대조](../build/web-review/prop-equation-results.json) |
| 소스 선언·속성·사용처 연결 | [속성 색인](../build/web-review/prop-results.json), [출력 사용처](../build/web-review/output-prop-results.json) |
| 기존 식 과제의 B·D 자료 | `build/web-pilot/materials/<과제>/B.md`, `D.md` |
| 사람 평가 계획 | [행동 표현 예행](evaluation/behavior-rehearsal.md), [보류한 본 파일럿 초안](evaluation/protocol.md) |

## 집계 규칙

- 행동 검토 문서 생성, 조건 표현의 IR 대조, 원본 실행, 원본 앱 실행, 브라우저 관찰, 사람 평가를 별도 집계한다.
- 기존 관찰을 다시 읽거나 재실행한 수를 새로운 사례·입력 범위로 합치지 않는다.
- 결합 원본 실행과 합성 수정 원본 실행은 별도 기록한다. 합성 수정은 실제 PR 사례 수에 합치지 않는다. 원본 앱 관찰을 결합 모델에 재대조한 수는 앱의 신규 실행 횟수가 아니다.
- 사례별로 사람이 정한 제목과 표현은 자동 행동 추론으로 표시하지 않는다.
- 사람 참가자는 현재 0명이다. 원래 고정한 기대 영향과 경계를 완성하지 못한 사례를 전체 행동 완료로 올리지 않는다.
- 과거 명령별 실행 기록은 [구현 기록](IMPLEMENTATION-HISTORY.md)에 보존한다. 이 문서는 현재 검증 성공이나 최신 엔진의 증거를 대신하지 않는다.
