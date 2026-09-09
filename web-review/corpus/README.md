# 실제 웹 변경 사례

선택일: 2026-09-09. 고정된 12개 사례는 서로 다른 공개 프로젝트 3개에서 가져왔다. 이 선택은 무작위 표본이나 시장 대표 표본이 아니다. 조건부 렌더·설정·상태·비동기·이벤트 문제를 포함하도록 고른 목적 표본이다. 특정 작성 도구로 만들어진 코드라고 일괄 분류하지 않는다.

| 파일 | 역할 |
|---|---|
| `selection.json` | 사례, 정확한 head, 관심 파일, 사람이 diff를 읽고 기록한 기대 영향 가설, 의미 경계 |
| `lock.json` | 변경 전후 커밋·blob·원본 SHA-256과 라이선스 파일. 선택 파일의 해시도 고정 |
| `slices.json` | 현재 자동 검사하는 네 지점, 입력 도메인, 독립적으로 작성한 기대 변경 조건 |
| `functions.json` | 원본에서 선택한 함수 본문과 별도 기대값 검사의 대응 |
| `guards.json` | 원본 JSX 표현식 안의 조건부 평가 경로와 별도 기대 조건의 대응 |
| `props.json` | 원본 설정으로 연결할 부모 JSX 속성·자식 매개변수의 기대 대응 |
| `references.json` | 저장 변수의 직접 JSX 자식 참조 두 곳과 객체 전달 관찰 |
| `flows.json` | 원본 JSX 생성과 const 저장·참조를 연결하는 전후 관찰 및 기대 조건 |
| `runtime-selection.json`·`runtime-lock.json` | React 실행 대조에 필요한 추가 원본 컴포넌트와 패키지 잠금 정보. 주 평가집의 분모를 바꾸지 않는다. |
| `dependency-audit.json` | 5개 사례의 수동 import 경로 대응, 사용 위치와 해석 한계 |
| `context-lock.json` | 5개 사례의 전후 tsconfig·package.json 및 전체 Git 추적 경로 목록의 해시 |

원본은 `build/web-corpus/`, 설정과 파일 목록은 `build/web-context/`에 복원한다. 각각 원본 프로젝트의 라이선스가 적용된다. Excalidraw와 Actual은 MIT, Jitsi Meet는 Apache-2.0이며 각 고정 버전의 LICENSE를 함께 복원한다. 원본 파일과 프로젝트 실행 결과를 섞지 않는다.

```powershell
python web-review/scripts/corpus.py fetch
python web-review/scripts/corpus.py verify
python web-review/scripts/context.py fetch
python web-review/scripts/context.py verify
cd web-review
npm.cmd run test:corpus
npm.cmd run test:context
npm.cmd run test:functions
npm.cmd run test:guards
npm.cmd run test:props
npm.cmd run test:references
npm.cmd run test:flows
python scripts/runtime.py fetch
npm.cmd run test:react
```

`freeze`는 최초 선택을 고정할 때 사용한 관리 명령이다. 기존 잠금 파일이 있으면 갱신하지 않는다. 수집 파일을 나중에 바꿔 성공률 분모나 기대 동작을 유리하게 고치는 대신, 변경 이유를 기록한 새 평가집 버전이 필요하다. `slices.json`은 구현 범위에 따라 추가되는 부분 검사 목록이며 고정된 12개 사례의 분모를 대체하지 않는다.

현재 네 부분 검사는 실제 원본을 분석하기 쉽게 고친 것이 아니다. 대신 원본의 선택한 지점에 도달했다는 전제에서 식별자의 값을 명시 입력으로 놓았다. 이 전제 때문에 전체 행동의 완료 수는 0/12로 보고한다. 모듈 색인과 실행 해석을 순수 프로젝트에서 결합했지만, 아직 실제 앱의 전체 행동을 설명하는 것은 아니다.

사람 검토 과제를 확정하려면 나머지 상태·이벤트 사례의 기대 동작을 재현하고 관찰 범위를 정해야 한다. AI 응답이나 작성자 추정만을 정답으로 삼지 않는다.
