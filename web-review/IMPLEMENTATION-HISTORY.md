> 방향 검토 이전의 구현·검증 기록을 보존한 문서입니다. 현재 계약과 다음 작업은 README.md와 CONTRACTS.md를 기준으로 합니다. 새로운 회귀 결과는 이 파일에 덧붙이지 않습니다.

# TypeScript·React 검토 실험

2026-09-09. 이 디렉터리는 웹 검토 언어의 의미 핵심과 추출 실험이다. **자유로운 한국어를 실행하는 언어나, 실제 React 앱 전체의 동작을 재구성하는 분석기가 완성된 상태는 아니다.** 현재 한국어 출력은 실행 IR의 설명이다. 사람이 더 쉽게 검토하는지는 아직 측정하지 않았다.

## 실행

Node.js 22 이상, Python 3.12를 사용한다. 기존 네이티브 `.gl`과 C G0의 의존성은 분리되어 있다.

```powershell
cd web-review
npm.cmd ci --ignore-scripts
npm.cmd test
python scripts/corpus.py fetch
npm.cmd run test:corpus
python scripts/context.py fetch
npm.cmd run test:context
npm.cmd run test:functions
npm.cmd run test:records
npm.cmd run test:arrays
npm.cmd run test:guards
npm.cmd run test:props
npm.cmd run test:references
npm.cmd run test:flows
python scripts/runtime.py fetch
npm.cmd run test:react
npm.cmd run prepare:pilot
```

Linux에서는 `npm.cmd` 대신 `npm`을 쓴다. `fetch`는 공개 저장소의 고정된 원본을 `../build/web-corpus/`에 복원하고 SHA-256을 확인한다. 수집과 분석은 대상 프로젝트 모듈을 실행하지 않는다. 별도 `test:react` 실행 대조에서는 고정된 React와 두 원본 컴포넌트 모듈을 실행한다. 최초 복원·의존성 설치에는 네트워크가 필요하며, `verify`는 잠금 파일을 변경하지 않고 준비된 원본과 설치된 의존성을 확인한다.

원본·문맥·추가 런타임 캐시를 준비한 뒤에는 `npm.cmd run verify:local`로 단위·CLI, 변경 목록 파서, 고정 원본, 실제 부분 실행, 브라우저 기록 재대조, 검토 자료 생성을 순서에 맞게 실행한다. 단계마다 엔진 해시가 같은지 확인하며 `build/web-review/verification/run-*/`에 각 로그와 결과를 남긴다. `verification-latest.json`은 마지막 **성공한** 실행을 가리킨다. 별도 원본 앱 작업 사본과 의존성도 준비했으면 `npm.cmd run verify:local -- --upstream`으로 원본 jsdom 실행까지 포함한다. 이때 checkout 충돌을 막기 위해 localhost:56678·56680의 복귀 버튼·색상 입력 브라우저 검증 서버를 먼저 중지해야 한다. 브라우저 기록 대조는 실제 브라우저 재실행이나 사람 평가가 아니다. 자료 재생성 후 예행 검토 서버도 다시 시작해 최신 자료를 읽힌다.

루트의 공통 진입점은 `python build.py web-review-test`, `python build.py web-review <명령>`이다. CI에는 독립 단위 검사를 추가했다. 공개 저장소를 받는 corpus 검사는 별도 명령이며 원격 CI에서 실행했다고 주장하지 않는다.

```powershell
python build.py web-review lift-expression --file sample.ts --expression "!busy" --out build/busy.json
python build.py web-review discover --file component.tsx --json
python build.py web-review discover --file component.tsx --kind const --limit 16 --offset 0
python build.py web-review discover-change --before before.tsx --after after.tsx --patch change.diff --json
python build.py web-review discover-change --before before.tsx --after after.tsx --patch change.diff --focus changed-lines --limit 16
python build.py web-review discover --file component.tsx --json --out build/candidates.json
python build.py web-review lift-candidate --file build/candidates.json --candidate 0 --out build/candidate.json
python build.py web-review read --file build/candidate.json
python build.py web-review lift-jsx-attribute --file component.tsx --tag button --attribute disabled --out build/disabled.json
python build.py web-review lift-jsx-guards --file component.tsx --tag button --attribute className --equals save --out build/save-path.json
python build.py web-review lift-jsx-reference --file component.tsx --name buttonElement --line 20 --out build/child-reference.json
python build.py web-review lift-jsx-flow --file component.tsx --tag button --attribute className --equals save --prefix-line 12 --out build/save-flow.json
python build.py web-review lift-project --file examples/web-review/delete-button/project.json --out build/delete-button.json
python build.py web-review lift-function --file source.tsx --function normalize --out build/normalize.json
python build.py web-review run --file build/delete-button.json --inputs examples/web-review/delete-button/inputs.json
python build.py web-review lift-project --file examples/web-review/delete-button/screen-project.json --out build/delete-screen.json
python build.py web-review run --file build/delete-screen.json --inputs examples/web-review/delete-button/screen-inputs.json
python build.py web-review run --file build/delete-screen.json --inputs examples/web-review/delete-button/screen-inputs.json --trace
python build.py web-review read --file build/delete-screen.json --out build/delete-screen-reading.md
python build.py web-review explain --file build/delete-screen.json --inputs examples/web-review/delete-button/screen-inputs.json --out build/delete-screen.md
python build.py web-review compare --before build/before.json --after build/after.json --domains inputs-domain.json --json
python build.py web-review index-props --file prop-project.json --out build/prop-bindings.json
python build.py web-review explain --file build/prop-bindings.json --out build/prop-bindings.md
```

`--out`은 기존 파일을 덮어쓰지 않는다. `run`·`compare`는 원본과 분석을 다시 읽어 IR·버전·해시까지 일치해야 실행한다. 실제 해석기 소스와 의존성 잠금 파일도 `engineSha256`에 결합한다. 원본·IR·해석기를 수정한 파일을 오래된 분석 결과로 사용할 수 없다. 오류·미지원·미확인은 종료 코드 2다. **변경이 발견된 것은 분석 실패가 아니므로 종료 코드 0**이며 결과의 `status`를 확인한다.

`read --file 분석.json`은 입력을 실행하지 않고 재검사한 IR의 가능한 계산·분기 구조를 한국어로 표시한다. 단락 평가·조건 분기의 생략, 계산 키의 순서, 지역 값의 범위, 필터의 반복을 구조에 남긴다. 일반 `&&`·`||`를 불리언으로 바꾸지 않으며 두 피연산자가 불리언 결과를 내는 지원 연산일 때만 간단한 그리고·또는 문장으로 표시한다. JSON 보기에는 모든 하위 연산·원본 위치·지역 바인딩 연결이 남는다. 자연어 자체가 실행 문법이거나 모든 입력의 실행·도달을 확인했다는 뜻은 아니다. 소스 연결 색인은 `read`로 실행 IR처럼 읽지 않는다. 기본 제한은 2,048개 IR 연산·깊이 64·설명 텍스트 262,144 UTF-16 코드 단위이며 초과하면 부분 설명을 완성본으로 반환하지 않는다. Actual 거래 선택의 `before-reading.md`·`after-reading.md`가 첫 실제 출력이다. 기존 사람 평가 과제 자료와 조건은 이 보기로 교체하지 않았다.

`compare`에는 `structureComparison`도 포함한다. 알려진 원본 위치·표시 이름만 제외하고 지역 바인딩의 범위를 보존해 IR 구조를 비교한다. 외부 입력 이름, 속성 순서, 문자열 데이터, 선택적 접근, 관찰 모드·배열 프로필을 같다고 뭉개지 않는다. 양쪽 결과 갈래 구조가 같은 조건 분기는 조건식 변경으로 따로 표시한다. Actual 거래 선택에서는 `!isSearching` → `!isSearching && !isFiltered`를 한 곳의 조건 변경으로 찾으며 `structure.md`에 원본 링크를 남긴다. 앞서 계산한 값이 바뀌면 같은 갈래 코드도 다른 결과를 낼 수 있으므로 이 구조 비교를 동작 동등성이나 변경 원인 전체의 증명으로 쓰지 않는다. 새로운 IR 필드나 노드·내용·변경 수 제한을 만나면 구조 설명을 미생성으로 남기며 원래 유한 실행 비교는 별도로 유지한다.

한국어 Markdown 읽기에서 연속된 저장·다음 계산은 같은 깊이로 표시한다. 초기화 식과 그 안의 분기는 해당 저장 아래에 남기고, 제어 분기는 명시적인 갈래 안에 후속 계산을 묶는다. 이 방식으로 지역 계산이 무조건 실행되는 단계처럼 바깥으로 빠지지 않게 한다. 사용하지 않는 초기화도 예외를 일으킬 수 있어 생략하지 않으며, 조기 반환 갈래에는 인수를 계산하지 않는다고 표시한다. JSON의 전체 연산·지역 범위·원본 연결과 실행 엔진은 그대로 유지한다. 읽기 형식 개선이 사람의 검토 성과 개선을 입증한 것은 아니다.

고정된 Actual 거래 선택 사례를 화면에서 살펴보려면 전체 검증 뒤 `npm.cmd run inspector`로 로컬 검토 작업대(`http://127.0.0.1:56679`)를 연다. 160개 입력 예시의 전후 목록·가능한 계산 구조·선택한 입력의 IR 기록·원본 위치를 함께 볼 수 있다. 사용법과 한계는 [작업대 설명](inspector/README.md)에 적었다. 기존 사람 평가 자료와 별개인 연구 시연이며 실제 Actual 앱 실행이나 사람의 검토 성능을 측정하는 화면이 아니다.

`read`와 `explain`은 입력 스냅샷에 대응하는 원본 선언도 연결한다. 구조 분해 이름은 그 이름의 조건부 기본값 식과 전체 패턴에 값을 주는 선언의 식을 구분한다. 예를 들어 `const { ready: enabled = fallback } = hook()`에서 `fallback`과 `hook()`은 서로 다른 원본 위치다. 중첩·배열·계산 키·나머지 속성이 있는 패턴은 원본 탐색으로만 표시하며, 이 색인 때문에 그 문법의 실행 지원 범위가 넓어지는 것은 아니다. JSON의 `inputBindings`에 같은 원본 정보가 남는다.

`npm.cmd run test:array-traces`는 현재 `test:arrays` 결과를 받아 Actual의 두 고정 선택식에 값 반환 probe를 삽입한다. 조건·단락 앞값·필터 원소 판단·filter와 concat 완료 길이를 원래 위치와 함께 기록한다. probe는 동일한 평가값을 그대로 반환하며 내장 filter·concat을 교체하지 않는다. 원본 344회와 계측본 344회를 별도로 실행해 결과와 TypeError가 같고, 공통 기록 996개의 순서·값·원본 구간이 IR 기록과 같은지 검사했다. 이 횟수는 기존 160개 입력쌍과 오류 입력 24개 버전 조합의 재실행이다. 새 입력 범위·새 사례·원본 앱 실행으로 집계하지 않는다. 임의 프로그램의 계측이나 저장·복사 세부 기록·스택·시간은 검증 범위가 아니다. 근거와 계측 소스는 `build/web-review/array-trace-results.json`, `build/web-review/native-traces/`에 생성한다.

## 관찰 범위

`npm.cmd run test:recording-guards`는 Jitsi의 `_renderSessionToggles`에서 `renderRecordingToggle`의 지역 const 계산을 지정한 녹화 `Switch` JSX 진입 조건에 연결한다. 불리언 8쌍 중 1쌍의 변화를 CLI로 비교하고, 이를 포함하는 JavaScript 값 1,728쌍에서 시험 환경의 원본 메서드 3,456회와 대조한다. 별도 10회는 선행 번역·대상 속성 getter·요소 생성기·뒤의 helper 예외를 넣은 반례다. 원본 메서드 본문을 TypeScript로 JSX 변환한 뒤 시험용 `this`와 기록용 요소 생성기를 공급하며 실제 React·Switch 구현·이벤트를 실행하지 않는다. 해당 파일에는 같은 ID의 Switch가 두 곳이므로 명시한 줄이 없는 추출은 거부한다. 읽기·계산·비교·반례와 환경 계약은 `build/web-review/recording-guards/` 및 `recording-guards-results.json`에 남긴다. 이 연결은 기존 녹화 조건식 사례를 확장한 부분 검사이며 전체 행동 완료 건수를 늘리지 않는다.

| 모드 | 현재 확인하는 내용 | 중요한 경계 |
|---|---|---|
| `expression-slice` | 선택 지점의 식 값·TypeError 발생 | 각 식별자는 그 지점의 외부 입력. 선언과 도달 조건을 추적했다고 하지 않는다. 같은 식이 여러 곳이면 거부하고 `--container`로 함수·메서드 이름을 지정할 수 있다. |
| `record-expression-slice` | 원본 객체 식의 자체 속성 값·속성 생략·TypeError | `lift-record --line`으로 객체 식 시작 위치를 고른다. 주변 호출·콜백·상태 갱신은 실행하지 않는다. |
| `prop-expression-slice` | 선택 부모 속성 식 → 자식의 선택 속성 식을 명시한 전달 가정으로 결합한 계산 | 일반 속성 전달을 가정한 방정식 모델이다. 다른 속성·hooks·매개변수 초기화·React를 실행하지 않는다. |
| `jsx-attribute-slice` | 해당 JSX 생성 지점에서 속성에 전달하는 값 | 지점 도달 조건·DOM 반영·실제 클릭 가능성은 미확인. 사용자 컴포넌트와 기본 태그를 표시상 구별한다. spread·중복 속성을 거부한다. |
| `jsx-property-slice` | 선택 JSX 속성의 생략·존재와 해당 식의 값 | 여는 태그를 먼저 고르므로 속성 추가·삭제도 비교한다. 결과는 선택 속성만 담는 관찰 레코드이며 실제 props·DOM은 아니다. |
| `jsx-guard-slice` | 한 표현식 안에서 대상 JSX 노드의 평가로 진입하는 조건 | 상위 `&&`·`||`·`??`·삼항 분기를 연결한다. 생략한 선행 태그·속성·형제가 정상 완료하고 조건 입력을 바꾸지 않는다는 가정이다. 노드 자신의 생성 성공·사용·화면 표시는 확인하지 않는다. |
| `jsx-reference-slice` | 직접 JSX 자식 자리에서 읽은 값이 null이 아닌 객체인지 | 참조 자리의 입력 스냅샷과 조건 경로를 관찰한다. 스칼라가 거짓 결과라는 것은 객체 전달이 없다는 뜻이며 `0`·문자열의 화면 표시가 없다는 뜻이 아니다. 해당 객체의 생성 위치·ReactElement 여부는 미확인이다. |
| `jsx-object-flow` | 선택한 JSX의 생성 조건을 저장·직접 자식 전달 경로와 연결한 결과 | 정상 JSX 생성을 가정한다. 인라인 전달 또는 같은 const의 객체/null 저장과 같은 블록의 한 return 표현식에 있는 참조를 연결한다. 내부 props·실제 React 렌더링은 미확인이다. |
| `function-body-slice` | 원본 파일에서 선택한 최상위 함수 선언 본문의 반환 데이터·TypeError 발생 | 전체 원본 파일을 해시에 결합하고 본문은 수정하지 않는다. 주변 코드·모듈 초기화는 실행하지 않으며 실제 호출이 이 선언을 사용한다는 사실은 미확인이다. 외부 값과 다른 함수의 바인딩을 가정하지 않는다. |
| `call-entry-slice` | 동기 함수 본문의 순수 선행 구간에서 마지막 호출 식 평가 직전까지 도달하는지와 선행 TypeError | 참·거짓은 도달 여부이며 함수 반환값이 아니다. 대상·인수 평가·실제 호출·효과는 제외한다. |
| `call-arguments-slice` | 같은 순수 선행 구간에서 조기 반환 또는 마지막 호출의 순수 인수별 값·TypeError | callee 식별자 읽기의 순수 정상 완료를 가정한다. 인수 값 스냅샷이며 실제 호출·반환·참조 동일성·효과를 증명하지 않는다. |
| `closed-pure-project` | 명시한 여러 지역 모듈의 순수 함수 반환 값·기본 태그 JSX 생성 구조·TypeError 발생 | TypeScript 심볼로 import 별칭과 호출을 연결한다. 선택적으로 고정된 설정 색인도 결합한다. 제공되지 않은 외부 모듈·React hooks·클래스·상태 변경은 거부한다. |

순수 프로젝트는 이름 있는 export 함수, 직접 지역 함수 호출, 이름 매개변수·제한된 객체 구조 분해, 지역 `const`, `if`, `return`, 순수 모듈 상수만 지원한다. 모듈 초기화 효과·type-only import의 실행 값 사용·재귀·순환 import·동적 호출·미지원 미사용 함수도 거부한다. 함수가 인수를 사용하지 않아도 인수 계산 순서와 오류 발생을 유지한다. 타입 단언은 값의 유효성을 확인하는 검사로 취급하지 않는다.

`lift-call-entry --file 코드.tsx --callee renameTag --line 69`는 이름을 가진 일반 직접 호출을 고른다. 대상은 동기 함수·화살표 함수·메서드 본문 블록의 마지막 직접 문장이어야 한다. 그 앞의 const·if·중첩 블록·값 없는 return을 순서대로 낮추며, 원시 문자열의 표준 trim·기존 순수 식·레코드를 지원한다. 값 있는 return, 대입, 다른 선행 호출, try·loop, async·generator, optional call은 거부한다. 선택 호출의 인수에 있는 미지원 코드는 제외한 구간으로 원본에 남긴다. 이것은 인수 실행 지원이 아니다. 본문 시작 전의 인수·매개변수 기본값·구조 분해도 이 모델 밖이다.

이 모드는 함수 본문 시작의 입력 스냅샷을 사용하고 지역 const는 TypeScript 심볼로 구분한다. 초기화 전 지역 값을 외부 입력으로 바꾸지 않으며, 조기 반환 뒤의 미지원 문장도 숨기지 않는다. 문장 128개·const 64개·중첩 32단계, 전개된 IR 65,536개·깊이 128의 제한을 둔다. ‘참’은 선택 호출 식 직전에 도달했다는 뜻이며 callee가 함수인지, 인수를 계산할 수 있는지, 호출이나 서버 요청이 성공하는지는 보장하지 않는다. read·run·explain·compare는 원본과 제외한 호출 메타데이터까지 다시 추출해 대조한다.

`test:call-entries`는 Actual의 변경 후 `onRename` 원본 callback을 그대로 시험용 입력·callee로 실행한다. 117개 입력에서 도달 37개·조기 반환 50개·선행 TypeError 30개를 대조했다. 이름이 비어 있으면 null tag의 속성을 읽지 않고 반환한다. callee가 함수가 아닌 경우·인수 getter 오류·callee 내부 오류는 별도 반례 3개이며, 숫자·불리언·객체 trim은 미지원 3개다. 원본 callback을 둘러싼 React·hook·키보드 이벤트·mutation·서버를 실행하지 않는다. 산출물은 `build/web-review/call-entries/actual-tag-rename-validation/`과 `call-entry-results.json`이다.

호출 진입의 `read`는 결과 위치에만 ‘조기 반환’과 ‘호출 식 직전 도달’을 표시한다. 조건식·const 초기값의 불리언에는 이 의미를 붙이지 않는다. 전후 `compare`도 이 경계로 결과를 읽으며 계산에서 제외한 양쪽 호출 인수의 원본을 함께 표시한다. 이름이 겹치는 저장값·filter 매개변수는 읽기 보기의 노드 번호로 구분해 선언과 참조를 연결한다. 이 번호는 실행 횟수가 아니다.

`audit:call-entries`는 고정 사례의 변경 후 파일에서 마지막 직접 문장이 이름 있는 호출인 함수 본문만 조사한다. 선행 문장 없는 후보·선행 문장을 IR로 추출한 후보·미지원 후보를 분리한다. 여러 사례에 반복된 파일 구간의 수와 바이트 해시·호출 위치로 중복 제거한 수도 별도로 제공한다. 전체 호출의 처리율·변경 줄 처리율·원본 실행 대조 성과가 아니다. 자세한 위치와 거부 이유는 `build/web-review/call-entry-candidate-audit.json`에 남는다.

호출 진입의 `sourceLinks`는 호출 이름의 선언과 해당 본문을 가진 함수의 같은 파일 안 직접 심볼 참조를 제공한다. 직접 const에 저장한 함수·이름 있는 함수 선언을 대상으로 하며, 다른 참조는 없는 것으로 추정하지 않는다. Actual의 `onRename`에서는 키 처리 본문의 직접 호출과 `InputCell.inputProps` 안의 `onUpdate` 참조 2곳을 원본 구문 조건·앞선 문장에 연결한다. `renameTag`의 `useRenameTagMutation()` 초기화 문맥도 소스 연결일 뿐이다. 별칭·다른 파일·속성 덮어쓰기·spread·실제 React 전달·이벤트 실행은 증명하지 않는다. 참조 128개, 문맥 2 MiB 한계를 명시하며 CLI는 이 메타데이터도 원본에서 다시 생성해 대조한다.

함수 매개변수와 지역 const의 객체 구조 분해는 고정 이름·문자열 키와 별칭을 지원한다. `const { a: value } = input`은 초기값을 한 번 계산한 뒤 속성을 순서대로 읽는다. 함수 호출은 모든 인수를 먼저 계산한 뒤 매개변수를 분해하며, 나중 인수의 계산 오류를 앞선 매개변수 분해 오류로 바꾸지 않는다. 빈 패턴·기본값·중첩·나머지 속성·배열·계산 키는 거부한다. 이름 없는 객체 인수에는 `인수1`처럼 충돌하지 않는 입력 이름을 주고 `parameterInputs`에 원본 매개변수 순서와 위치를 기록한다. 분해해 읽은 값은 한국어 실행 설명에도 표시한다.

두 함수 모드에서는 고정 이름·단축 속성·제한된 spread를 사용한 객체 생성과 인수 없는 표준 문자열 `trim()`을 지원한다. 일반 속성의 중복은 적힌 순서대로 모두 계산하고 뒤 값이 앞 값을 덮어쓴다. 객체의 고유 데이터 속성만 관찰하며 속성 순서·프로토타입·동일성은 관찰에서 제외한다. 생성한 객체에서 없는 속성을 읽으면 프로토타입을 임의로 없던 것으로 처리하지 않고 미지원으로 남긴다. 접근자·계산한 생성 키·`__proto__: 값`의 prototype 설정은 거부한다. 단축 속성 `{ __proto__ }`와 spread로 복사한 자체 `__proto__`는 데이터 속성이다. `trim`은 원시 문자열과 변경되지 않은 표준 구현을 가정하며, 객체의 사용자 정의 메서드를 대신 실행하지 않는다. 이 가정은 실행 설명과 비교 결과에도 표시한다.

`lift-jsx-guards`의 `--line`은 여는 태그의 줄을 선택한다. `--attribute`와 `--equals`는 소스에 명시된 문자열 속성으로 노드를 식별하는 선택자이며 런타임 속성값을 증명하지 않는다. 평가 시작점은 선택 노드를 포함한 변수 초기화 식, return 식 또는 화살표 함수 본문이다. 그 앞의 조기 반환과 함수 호출 여부는 별도다. 생성한 요소를 지역 변수에 저장한 경우 사용처까지 자동으로 연결했다고 하지 않는다. 생략한 평가를 원본 위치와 함께 결과 및 `explain`에 표시한다.

`lift-jsx-property --file 원본.tsx --tag input --attribute aria-invalid`는 속성이 없어도 선택한 태그에서 그 사실을 관찰한다. 같은 태그가 여러 개이면 `--line`에 **여는 태그의 시작 줄**을 지정한다. 기존 `lift-jsx-attribute`의 속성 줄 선택과 구별한다. 속성 생략은 빈 관찰 레코드, 명시한 undefined·null·false·값 없는 속성은 해당 필드가 있는 레코드로 유지한다. 레코드는 선택 속성만 투영한 결과이며 전체 props가 아니다. spread·중복 선택 속성·빈 JSX 식·key/ref/children 같은 특수 속성을 거부한다. 식별자는 해당 평가 지점의 스냅샷이라는 기존 속성 식 계약을 따르므로 이름 `undefined`도 자동 전역 상수로 치환하지 않는다.

`test:jsx-properties`는 Excalidraw 색상 입력의 aria-invalid 추가를 다룬다. 원본의 선택 속성만 남긴 별도 JSX 조각 26회와 독립 실행기를 대조하고, 고정한 React 19.0.0의 별도 기본 input 실험 26회로 HTML 속성을 관찰한다. 원본 ColorInput과 그 런타임을 실행한 결과는 아니다. 13개 입력 모두 속성 존재가 바뀌지만 [WAI-ARIA 1.2](https://www.w3.org/TR/wai-aria-1.2/#aria-invalid)는 속성 없음과 false를 기본 false로 해석하므로 선언상 invalid 상태의 차이는 6개다. 원본의 string|null 타입 모양에 맞춘 입력 5개에서는 3개다. 이 규범 해석을 실제 보조 기술의 실행 결과로 세지 않는다. [React의 ARIA 속성 지원](https://react.dev/reference/react-dom/components/common#common-props)과 실제 오류 상태의 정확성·접근성 동작은 별개다. 결과는 `build/web-review/jsx-properties/excalidraw-color-invalid-property/`와 `jsx-property-results.json`에 남긴다.

별도 `test:upstream-color`는 같은 변경의 원본 앱에서 수동으로 정한 9개 입력 경로를 전후 실행한다. 100개 DOM·배경색 관찰, 대응하는 50개 전후 상태에서 입력 표시 차이 4개와 오류 안내 추가 12개를 확인했다. 기존 속성 IR에는 DOM에서 추출한 정답 대신 시나리오의 예상 메시지를 넣어 속성을 조건부로 대조한다. hooks·이벤트를 해석하는 글 모델을 추가한 것은 아니다. 원본 jsdom 환경·정확한 준비 방법·의존성 해시는 [통합 실행 설명](upstream-tests/README.md)에, 최신 성공 실행과 읽을 수 있는 비교표는 `build/web-review/upstream-color-results.json`에 연결한다. 입력이 비어 있다는 사실과 저장된 색이 초기화됐다는 주장을 구분한다.

색상 입력의 실제 브라우저 기록은 `check:color-browser-recording`으로 재검사한다. 원본 전후 36개 관찰의 커밋·화면 자산·기록을 결합하고, 18개 대응 단계의 입력 표시 차이 4개와 오류 안내 추가 6개를 구분한다. 이 명령은 브라우저 재실행이 아니다. 비교표는 `build/web-review/color-browser-comparison.md`다. 핵심 검사 파일은 `npm test`와 전체 검증 모두 최대 4개씩 병렬 실행해 원본 VM의 짧은 제한과 검사 실행 부하를 분리한다. 네이티브 100ms 제한 자체는 완화하지 않는다.

경로의 `bindings` 색인은 입력 이름의 실제 선언과, 표현식 결과를 저장하는 지역 변수의 참조 위치를 TypeScript 심볼로 연결한다. 동일 이름의 다른 지역 변수, 다른 함수가 캡처한 참조, 타입 참조, JSX 자식 참조를 구별한다. 초기화 식도 원본 링크로 제공하지만 그 식을 나중 시점에 다시 계산해 입력을 대신하지 않는다. 객체가 그 사이 바뀔 수 있기 때문이다. Excalidraw 모바일 원본에서 버튼 변수의 JSX 자식 사용 2곳과 조건 연산 참조 1곳을 확인했다. 이는 사용처를 찾아 준 것이며 해당 사용의 실행 경로·화면 표시를 검증한 것은 아니다.

별도의 `lift-jsx-reference`는 `--name`과 필요시 `--line`·`--column`으로 직접 자식 참조를 고른다. `lift-jsx-flow`는 생성 노드를 `lift-jsx-guards`와 같은 선택자로 고른다. 저장 흐름에서는 `조건 ? 선택JSX : null` 또는 반대 배치만 지원한다. `--prefix-line`부터 const를 순서대로 계산하고 생성 결과를 객체 또는 null로 투영해 동일한 바인딩의 참조에 전달한다. 뒤쪽 참조 조건은 같은 블록에서 이미 초기화한 const만 읽을 수 있다. 객체 내부 재조회·다른 함수 캡처·별칭·여러 return·중간 제어 분기는 거부한다. 저장과 return 사이의 식 문장은 정상 완료를 명시적으로 가정해 목록에 남긴다. 원본 객체가 바뀌어도 이전에 계산한 const를 다시 계산하지 않는다. 정상 JSX 생성과 생략한 평가의 정상 완료는 증명 결과가 아니라 이 관찰의 가정이다.

`--prefix-line`을 지정하면 같은 블록에서 그 줄부터 선택 표현식 앞까지 연속된 `const` 초기화를 원본 순서로 실행한다. 이 모드의 외부 입력은 구간 시작점의 스냅샷이다. 지역 값은 심볼로 연결하고, 사용하지 않는 초기화도 실행한다. 중간의 호출·대입·분기나 초기화 전 지역 값 읽기를 임의로 건너뛰지 않는다. 단순 이름의 const 1~64개만 지원하며, 시작 구간 앞의 실행과 JSX 경로에서 생략한 형제의 효과는 여전히 별도다.

기본 태그 JSX를 반환하는 순수 함수에서는 `if`에 따른 조기 반환, 다른 파일의 판정 함수 호출, 속성과 자식의 계산 순서를 연결한다. 조건이 `0`이면 `0 && <button/>`의 결과를 거짓이나 `null`로 바꾸지 않는다. 출력의 `$jsx`는 생성 구조의 관찰값이며 실제 ReactElement 인스턴스나 DOM이 아니다. 이 순수 함수 관찰은 TypeScript를 JS로 변환한 뒤 JSX 생성 인자를 기록하는 테스트 함수와 대조한다. 실제 React 서버 렌더링을 사용한 별도 원본 흐름 실험의 범위는 아래에 명시한다. 사용자 컴포넌트·fragment·이벤트 콜백·`key`/`ref`/`children` 특수 속성·spread·HTML entity·여러 줄 비어 있지 않은 JSX 텍스트는 순수 함수 모드에서 거부한다. JSX 출력 태그를 입력 값으로 다시 넘기는 경로도 현재 계약 밖이다.

프런트엔드는 JavaScript Compiler API를 고정해 재현하기 위해 TypeScript **5.9.3**을 사용한다. 최신 버전 추종과 분석기 의미의 재현성은 별도 작업이다. 의존성 무결성은 `package-lock.json`에 고정한다.

설정을 결합하는 프로젝트 manifest는 `context`를 추가한다. `inventory.json`은 원본 버전에서 추적된 전체 상대 파일 경로의 JSON 배열이며, 내려받은 코드만 나열한 목록으로 대체하지 않는다. `metadata`의 원본 설정·package.json을 그대로 읽는다. 이 자료가 부족하면 import를 임의로 대체하지 않고 거부한다.

```json
{
  "files": ["src/screen.tsx", "src/policy.ts"],
  "entry": "src/screen.tsx",
  "functionName": "Screen",
  "context": {
    "metadata": ["tsconfig.json", "package.json"],
    "inventory": "inventory.json",
    "configPath": "tsconfig.json"
  }
}
```

JSX 의미 해석은 표준 React 생성 프로파일에 한정한다. 사용자 JSX factory·import source·파일 pragma와 JSX preserve 상태에서 선택되지 않은 변환기는 미지원이다. 설정 색인이 이들 설정을 읽을 수 있어도 실행 의미까지 지원하는 것은 아니다.

## 파일 사이의 속성 연결 색인

`index-props`는 원본 tsconfig·package.json으로 부모의 JSX 태그를 자식의 함수 선언과 연결하고, 명시한 속성이 어느 구조 분해 매개변수 이름에 대응하는지 보여 준다. import 별칭·중간 재수출·지역 이름 가림을 심볼로 처리한다. 타입 전용 import·export, wrapper·클래스·가변 함수, JSX spread·중복 속성, 중첩 구조 분해·React 특수 속성은 성공으로 처리하지 않는다. 매개변수 기본값은 원본 식의 위치를 별도로 표시하며 실행 결과를 계산하거나 부모 값과 같다고 간주하지 않는다. 실행 함수 모드의 기본값 지원과는 구분한다.

자식 함수에서 같은 매개변수 바인딩을 사용하는 위치도 연결한다. 다른 JSX 속성으로 전달하는 참조, JSX 조건식 안의 참조, 재대입·증감, 타입·기타 참조, 다른 함수의 캡처를 구별하고 같은 이름의 별도 지역 바인딩은 제외한다. 참조는 변수당 2,048개·전체 16,384개 이내다. 원본 식과 연결 위치를 보여주는 색인이며, 앞선 hooks·객체 변경·기본값 실행·콜백 시점 이후에도 부모의 값이 유지된다고 증명하지 않는다.

연결 명세의 `includeAbsent: true`는 부모 JSX에 생략된 속성도 선택하도록 한다. spread가 있으면 생략을 확정하지 못하므로 거부한다. 산출물은 `provided: false`와 `source-omission-linked`를 기록하며 `undefined` 같은 런타임 값을 만들지 않는다. React 생성기·기본 속성·실제 함수 호출을 확인하지 않았기 때문이다. 명시된 속성 연결 수와 생략 확인 수는 별도로 집계한다.

`lift-prop-expression --file 명세.json`은 같은 파일·설정 명세에 `assumePlainProps: true`와 `sink: { "tag": "TransactionList", "attribute": "isLoading" }`를 명시한 경우, 선택 부모 속성 식을 자식의 해당 속성 식에 대입한 실행 모델을 만든다. 이는 자동으로 확인한 React 전달이 아니다. 생략된 속성은 이 모델에서 undefined로 둔다는 가정을 분명히 표시한다. 선택한 부모 식은 원본 JSX 순서로 모두 한 번씩 계산하므로 자식 식의 단락 평가 때문에 앞선 인수 오류가 사라지지 않는다. 기본값이 있는 선택 매개변수, 캡처·재대입·기타 사용, 다른 함수의 sink, 선택한 매개변수 밖의 자식 입력은 거부한다. 생성한 객체를 전달할 때도 미확인 prototype 경계를 유지한다. `run`·`explain`·`compare`는 명세·소스·선택 sink·IR·엔진을 재확인한다.

`test:prop-equations`는 Actual의 로딩 전달 모델을 16개 입력 조합과 원본에서 선택한 식의 네이티브 결합 계산 32회로 대조한다. 필터가 있고 검색하지 않는 경우 로딩 출처가 달라지는 두 조합이 자식 TransactionList.isLoading 계산에도 연결된다. 전체 원본 컴포넌트 실행 수로 세지 않는다. PullToRefresh.isPullable 경로는 onRefresh의 async callback 캡처 때문에 전후 모두 거부하며, 예상 변경 없음이라는 가설을 성공으로 세지 않는다. 지원 결과와 거부 위치는 `build/web-review/prop-equation-results.json` 및 `prop-equations/`에 따로 남는다. 다른 부모 속성이나 자식 본문이 오류를 던지면 이 부분 모델이 값을 계산해도 전체 실행은 실패하는 반례를 시험에 포함했다.

manifest는 위 프로젝트 형식의 `files`, `entry`, `context`와 함께 `tag`와 `properties`를 지정한다. 예를 들어 `"tag": "MobileMenu", "properties": ["appState", "defaultUIEnabled", "scrollBackToContentUIEnabled"]`이다. 같은 태그가 여러 곳이면 `line`으로 여는 태그를 선택한다. `functionName`은 이 명령에 필요하지 않다.

이 결과의 모드는 `component-prop-bindings`이며 실행 IR이 없는 탐색 색인이다. `explain`은 입력 JSON 없이 원본 연결 표를 만들고 `run`·실행 비교는 거부한다. 속성 식의 값, React의 실제 호출, hooks 이후 입력 불변은 아직 증명하지 않는다. 이 연결만으로 서로 다른 시점의 스냅샷을 같은 값으로 합치지 않는다.

## 값과 비교 계약

스칼라, `undefined`, `NaN`, 무한대, `-0`, 문자열 속성을 가진 값 레코드를 지원한다. 속성 이름은 고정 문자열이거나 `records[selected]`처럼 지원 식으로 계산한 **원시 문자열**이어야 한다. 숫자·객체 등 다른 키의 암묵 변환은 지원하지 않는다. 기본 값을 먼저 읽고 키 식을 계산하며, `?.[key]`가 nullish 기본 값에서 중단되면 키 식도 계산하지 않는다. 키 입력은 의존성·비교 도메인·소스 색인·실행 기록에 포함한다. 속성 경로는 깊이 128에서 제한한다. [속성 접근의 평가](https://tc39.es/ecma262/multipage/ecmascript-language-expressions.html#sec-property-accessors-runtime-semantics-evaluation), [선택적 체인의 평가](https://tc39.es/ecma262/multipage/ecmascript-language-expressions.html#sec-optional-chains-runtime-semantics-evaluation)를 참고하되, 객체 키 변환이나 모든 ECMAScript 객체 의미를 구현했다고 하지 않는다.

`&&`·`||`는 피연산자를 반환하고 `??`는 nullish 값만 대체한다. 선택적 체인의 중간 중단과 괄호에 따른 경계, 평가 순서를 보존한다. `==`·`!=`는 우변 `null`만 지원한다. 객체끼리의 동일성·객체의 암묵 변환·함수·심볼·bigint는 지원하지 않는다. 배열은 기본 프로필에서 거부하며, 아래의 명시적 const 구간 배열 프로필에서만 지원한다.

입력은 다음과 같이 JSON으로 전달한다.

```json
{
  "user": { "$record": { "role": "admin", "suspended": false } },
  "owner": false,
  "locked": false,
  "optionalValue": { "$value": "undefined" }
}
```

`$value`의 다른 태그는 `NaN`, `Infinity`, `-Infinity`, `-0`이다. 레코드는 모든 자체 속성이 열거 가능한 데이터 속성인 null 프로토타입 객체로 복원한다. `encode`는 열거 불가능한 속성을 이 프로파일로 잘못 바꾸지 않도록 거부한다. **실제 React props에 getter·Proxy·프로토타입·객체 별칭이 없다는 사실은 자동 증명하지 않는다.** 이 계약에 맞는 입력 스냅샷만 비교한다. 오류는 `TypeError` 발생 여부까지 관찰하며 메시지·스택·발생 위치의 동일성은 보증하지 않는다.

`{"$opaque":"truthy-object"}`는 구조를 모르는 객체를 나타내는 명시적 입력 가정이다. 참 취급·nullish 여부·`typeof object`만 알며 속성 읽기·암묵 변환·객체 동일성은 지원하지 않는다. 이 값을 관찰 결과로 직접 반환하거나 레코드에 넣어 반환하면 미확인이다. 모르는 내부를 빈 객체로 바꿔 반환 값이 같다고 판정하지 않는다. 흐름 모드는 선택 JSX가 정상 생성됐을 때 이 투영을 내부 값으로만 사용하고, 최종 객체 전달 여부를 불리언으로 관찰한다.

비교 도메인은 각 입력의 후보 값 배열이다. 합성한 직적곱을 전부 실행하되 최대 65,536조합, 전개 IR 노드×조합 수 800만, 입력 처리량 추정 128 MiB로 제한한다. 동적인 filter 반복, 배열·레코드 복사, 문자열 처리도 전후·모든 조합이 공유하는 작업 단계 예산 800만에서 차감한다. 각 관찰의 실행 단계 제한 10만은 별도로 유지한다. `executionWork`는 노드 방문·순회·복사·문자열 처리에 예약한 단계이며 실제 시간이나 메모리 사용량의 측정값은 아니다. 전체 예산을 넘으면 일부만 검사한 결과나 미확인 행 목록을 완료본으로 반환하지 않고 오류로 중단한다. API로 예산을 줄일 수 있지만 기본 상한을 넘기거나 NaN·Infinity를 지정할 수 없다. 결과의 `equal-in-declared-domain`은 이 명시한 범위에서만 같다는 뜻이다. 입력 범위 밖까지 동등하다는 뜻이 아니다. 지원하지 않는 값 조합은 `unknown`으로 남기고 전체 결과를 `inconclusive`로 만든다.

값 문자열과 레코드 속성 이름은 최대 1,048,576 UTF-16 코드 단위다. 연결 결과는 새 문자열을 할당하기 전에 길이를 검사한다. 문자열 연결·비교·숫자 변환·trim은 처리할 문자열의 코드 단위 수를 보수적으로 작업 예산에 예약하므로 길이 상한 이하라도 한 관찰의 예산을 넘으면 미지원으로 끝날 수 있다. truthiness와 typeof처럼 내용을 순회하지 않는 관찰에는 이 문자열 처리 비용을 붙이지 않는다. 짧은 const 코드가 문자열을 반복해서 두 배로 늘리는 경우도 큰 중간 결과를 만들기 전에 중단한다.

관찰 값을 데이터 트리로 펼칠 때는 131,072개 값 노드와 보수적인 JSON 용량 추정 8 MiB를 상한으로 둔다. 같은 객체를 여러 속성에서 참조하는 작은 함수도 출력은 기하급수적으로 커질 수 있으므로, 깊이 제한만으로 처리하지 않는다. 상한을 넘으면 미지원으로 반환한다. CLI 분석 파일과 출력은 16 MiB, 원본과 입력 JSON은 2 MiB 이내이며 쓰기 전에 출력 크기를 확인한다.

`compare`의 `changeRules`는 같은 변경 전후 관찰을 내는 입력들을 유한 도메인의 규칙으로 묶는다. 다른 모든 축이 같을 때 한 축의 허용 값 집합을 합치고, 생성된 규칙을 원래 입력 행으로 다시 펼쳐 빠짐·겹침·미확인 입력 포함 여부와 결과를 검사한다. 규칙에서 생략한 입력은 **명시한 도메인 안에서만** 제한하지 않는다는 뜻이다. 객체에 대해 관찰하지 않은 값까지 성질을 일반화하지 않는다.

`changeConditions`는 결과값이 서로 달라도 **차이가 생긴 입력**을 함께 묶는다. 각 조건에는 단일 전후 값을 넣지 않고 해당 입력 수와 서로 다른 결과 쌍 수를 기록한다. 원래 변경 행을 기준으로 별도 검증해 미변경·미확인 입력 포함, 중복, 누락을 거부한다. `envelope`는 모든 변경 입력을 포함하는 축별 공통 범위이며, 그 안의 변경·동일·미확인 개수를 함께 표시한다. 공통 조건이 변경의 충분조건이라고 주장하거나 변경 원인·도메인 밖 입력으로 일반화하지 않는다. Actual 거래 선택의 고정된 160개 입력에서는 전후 값별 규칙 34개를 변경 조건 두 개로 묶으며, 공통 범위인 `isFiltered=true`, `isSearching=false`의 40개 입력 중 34개는 바뀌고 6개는 같다. 두 불리언 축의 256개 결과표를 독립적인 셀 포함 검사로 확인한다. 이 요약은 검토 자료의 표현 개선이며 사용자 검토 시간 감소를 입증한 결과가 아니다.

전후 관찰이 값 레코드이면 한국어 비교 설명은 속성 추가·삭제·값 변경을 분리한다. `amount`가 없는 것과 `amount: undefined`, `0`과 `-0`, `a.b`라는 단일 이름과 중첩 경로를 구별한다. 만든 변경 목록을 이전 관찰에 다시 적용해 이후 관찰을 정확히 복원하는지 검사한 경우에만 나머지 관찰 필드가 같다고 표시한다. 64개 변경·16,384 작업·깊이 32·보수적 문자열 용량 1 MiB 제한 또는 미지원 값에 걸리면 부분 목록을 완전한 요약으로 제시하지 않고 원래 전후 결과 표시를 유지한다. 이 목록은 관찰 데이터의 차이이며 소스 수정 패치가 아니다.

규칙 생성은 입력 이름 16개, 변경 행 8,192개, 묶기 작업량 200만을 제한으로 둔다. 작업량이 끝나도 모든 변경을 덮는 유효한 현재 규칙 집합을 검사해 반환하며 최소 규칙 수는 보증하지 않는다. 같은 관찰 값을 중복한 도메인이나 생성 제한에 걸린 경우 원래 행 비교를 유지하고 규칙 미생성 이유를 표시한다. 두 불리언 입력의 256가지 결과 표에서 알려진 변경·서로 다른 결과·미확인 구멍을 확인했다. 실제 네 부분 사례의 8개 변경 행은 현재 6개 규칙이 되며, 이 수치는 사람의 검토 성능 측정이 아니다.

같은 필드 구조를 가진 레코드 입력은 표시할 때 필요한 필드 조건으로 풀어 쓴다. 이때도 원래 도메인의 모든 값에 필드 조건을 적용해 정확히 같은 입력을 선택하는지 다시 확인한다. 예를 들어 `(a=false,b=false)`와 `(a=true,b=true)`만 선택한 상관관계를 `a·b 아무 값`으로 풀어 버리지 않는다. 필드 존재 여부가 다르거나 내부 미확인 객체를 포함하면 원래 객체 조건을 유지한다. 표시를 줄였다는 이유로 입력 범위 밖까지 일반화하지 않는다.

`run --trace`는 선택한 분기, 단락 평가에서 생략한 우변, 지역 값 저장, JSX 생성, 속성 읽기 오류를 원본 위치와 함께 기록한다. 실행기가 실제 방문한 경로의 기록이며 AI가 추측한 설명이 아니다. 기록은 최대 512개이고 생략 여부를 `traceTruncated`로 알린다. 큰 레코드·문자열은 미리보기만 기록하며 전체 실행 결과는 별도로 유지한다. 이 기록이 기획 의도나 올바른 사용자 경험을 판단해 주는 것은 아니다.

`explain`은 같은 실행 기록을 한국어 Markdown과 원본 파일 링크로 표시한다. 이 출력은 아직 실행 문법으로 되읽는 글 소스가 아니며, 사람이 읽기 좋은지 시험할 첫 표시 형식이다. `--json`으로 동일 실행의 구조화된 기록을 받을 수 있다.

## 실제 사례와 현재 증거

`corpus/selection.json`은 Excalidraw·Jitsi Meet·Actual의 실제 변경 12개를 고정한다. `lock.json`에 부모/변경 커밋, 원본 blob, SHA-256, 라이선스 파일을 기록했다. 현재 82개 원본 blob이 복원·검사된다. `dependency-audit.json`에는 5개 사례의 여러 파일 연결을 수동으로 대응시키고 import 선언과 사용 위치를 확인했다. 이는 자동 모듈 해석 성공 수치가 아니다.

`slices.json`의 네 지점에서 40개 입력 조합을 비교하며, 변경 전후 원본 식의 80회 실행을 독립 IR 실행과 대조한다. 순수 함수 모듈 검사는 별도의 작성된 수용 사례다. **실제 사례 12개 중 전체 행동을 재구성·검증한 사례는 아직 0개다.** 미지원 사례를 분모에서 빼지 않는다.

`functions.json`에서는 Actual 원본의 `resolveStartingSettings` 선언 본문을 추출한다. `test:functions`는 362개 입력에서 원본 본문의 JS 실행, 독립 IR 실행, 별도로 작성한 기대값을 대조한다. Unicode 공백, 빈 날짜, 공백을 포함한 유효·비유효 날짜 문자열, 누락된 잔액과 0·-0·NaN 등을 포함하며 날짜 자체의 유효성을 검증한다고 하지 않는다. 잘못된 trim 수신자 3개는 미지원으로 확인한다. 결과와 원본 링크가 있는 설명은 `build/web-review/function-results.json`, `build/web-review/functions/actual-resolve-starting-settings/`에 생성한다. 이 함수는 변경 후에 추가됐으므로 이 검사를 변경 전후 전체 기능 비교로 세지 않는다.

`guards.json`은 Excalidraw 한 변경 사례의 데스크톱·모바일 파일에서 전후 네 표현식 경로를 검사한다. `test:guards`의 192개 입력에서 수작업 기대 조건과 일치하고, 방문한 원본 조건식을 258회 실행해 대조했다. 선행 JSX 전체를 실행한 검사는 아니다. 별도 합성 코드에서는 원본 JSX 표현식 전체를 표준 생성기 대역으로 실행해 972개 입력과 비교했다. 모바일 변경 후 버튼은 변수 초기화에서 생성되므로 이 시점의 조건을 이전 return 식과 바로 비교해 화면 변화라고 부르면 안 된다. `build/web-review/guard-results.json`과 `build/web-review/guards/`에 이 경계와 원본 연결을 남긴다.

같은 모바일 원본의 121줄부터는 두 선행 const를 포함하는 다섯 번째 경로도 검사한다. 68개 입력에서 원본 const 구간의 JS 실행과 일치했고, 누적 경로 입력 검사는 260개다. JSX 생성기와 번역 함수 `t`는 정상 동작하는 테스트 대역을 사용했으며 실제 React·번역 런타임을 검증한 것은 아니다. 이 구간에서 도출된 값은 더 이상 외부 입력으로 넘기지 않는다. 지역 계산을 포함했다고 앱 전체 동작의 완료 수를 올리지 않는다.

`test:references`는 같은 원본의 직접 자식 참조 두 곳을 24개 입력에서 대조한다. `test:flows`는 변경 전 인라인 전달과 변경 후 const 저장·참조 연결을 비교한다. `mobile-flow-inputs.json`에 기존 불리언 대조군과 메뉴의 문자열/null·사이드바의 객체/null 형태에 맞춘 부분 스냅샷을 각각 64조합씩 지정했다. 각 도메인의 두 변경 조합은 보기 모드·화면 밖·메뉴/사이드바 닫힘·해당 UI 활성이라는 규칙 하나로 묶인다. 기본 UI 활성 여부는 해당 유한 도메인에서 제한하지 않는다. 원본 구간 실행과의 대조는 전후 각 128회, 변경 후 중간 객체 변경 128회, 전후 nullish 입력 각 8회로 총 400회다. 결과는 `build/web-review/flow-results.json`과 `build/web-review/flows/excalidraw-mobile-scroll-flow/`에 생성하며, 기본 `comparison.md`는 문자열·객체·null 도메인이고 불리언 대조군은 별도 파일로 보존한다. 이 부분 객체가 전체 AppState 타입을 만족하거나 실제로 도달 가능하다고 증명하지 않는다. 전체 행동은 0/12, 사람 평가는 미실시다.

`test:react`는 원본 전후 `yarn.lock`과 같은 React·React DOM **19.0.0**, clsx **1.1.1**, scheduler **0.25.0**을 사용한다. `runtime-selection.json`과 별도 잠금 파일로 원본 `Island`·`FixedSideContainer`도 고정하고, 두 모듈을 수정하지 않은 채 TypeScript 변환 후 허용한 의존성만 연결해 실행한다. MobileMenu의 선택한 원본 구간을 이 컴포넌트와 서버 렌더러로 실행해 두 입력 도메인에서 HTML의 대상 버튼 개수를 384회 대조했다. 버튼 경로의 두 부모는 실제 원본이며, 다른 helper·MobileShapeActions·번역 등은 결과 JSON에 명시한 대역이다. CSS import는 실행하지 않는다. 브라우저 배치·가림·hydration·클릭·실제 상태 도달을 검증한 결과가 아니다.

부모 대역이 자식을 버리는 경우와 앞선 helper가 예외를 내는 경우도 전후 각각 재현했다. 이때 객체 전달 모델의 참 결과를 HTML 표시 보장으로 해석하면 틀린다. 네 반례는 분석기의 지원 계약 밖 조건을 구체적으로 보여 주며 정상 입력 성공 수에 합산하지 않는다. 상세 근거는 `build/web-review/react-results.json`, HTML 표본은 `build/web-review/react/excalidraw-mobile-scroll-flow/`에 남는다. 추가 런타임 파일은 `build/web-runtime/`에 복원하며 기존 12개 사례의 분모는 변경하지 않았다.

`test:props`는 Excalidraw의 LayerUI → MobileMenu 전후 연결 6개와 Actual의 AllAccountTransactions → TransactionListWithBalances 전후 연결 5개를 확인한다. 두 사례의 원본 문맥 4개·명시된 소스 연결 11개·onRefresh 생략 확인 2개이며 실행 검증 수가 아니다. Actual의 isLoading이 자식의 PullToRefresh.isPullable 식과 TransactionList.isLoading에 쓰이는 위치, 변경 후 filtered 기본값과 필터 표시 식을 추적한다. 원본·설정·전체 경로 목록·라이선스를 `build/web-review/prop-projects/`에 묶고 CLI로 재검사한다. 수정된 원본 복사본을 덮어쓰지 않는다. 결과는 `build/web-review/prop-results.json`과 각 묶음의 `prop-bindings.md`에 남으며, 해당 분석 밖 변경 파일도 표시한다.

`context-lock.json`은 위 5개 사례의 변경 전후 10개 문맥에 tsconfig·package.json·추적 파일 목록을 결합한다. `test:context`는 TypeScript의 설정 상속, `paths`, `moduleSuffixes`, package `imports`를 적용해 선정된 연결 10개를 재확인한다. 경로만 알고 내용을 받지 않은 파일은 `resolved-unloaded`, 설정 메타데이터가 빠졌으면 `unconfirmed-metadata`로 남긴다. 외부 패키지는 설치하지 않아 상당수가 `unresolved-in-snapshot`이며 전체 모듈 그래프가 완성된 것은 아니다. 설정의 플러그인·패키지 scripts는 실행하지 않는다. 색인은 실행 의미 해석과 별도다.

결과는 `build/web-review/corpus-results.json`에 생성된다. 기존 원본과 사람 작성 기대 조건을 사용하며, 분석 결과에서 기대 정답을 역으로 생성하지 않는다. 프로젝트 전체를 실행하는 대신 지정된 순수 원본 식만 테스트 실행기에 전달한다. 이 실행 검사는 의미 보존에 대한 유한 실험이며 정형 증명이 아니다.

`test:upstream`은 [별도 원본 작업 사본](upstream-tests/README.md)에서 두 커밋의 전체 앱과 원래 Vitest/jsdom 설정을 실행한다. 16개 시나리오의 102개 상태에서 대상 버튼 DOM 개수가 객체 전달 모델과 일치하고, 원본 이벤트 처리기를 통한 복귀 클릭 6회에서 콘텐츠 밖 상태가 해제됐다. 메뉴·사이드바는 테스트 API로 연 상태이며, 원본 테스트 환경의 canvas·font·ResizeObserver 대역도 명시한다. 원본 변경은 TSX 두 파일과 CSS 한 파일로 총 세 파일이다. CSS까지 같은 커밋으로 검사하지만 jsdom의 DOM 존재를 실제 배치·가림 검증으로 취급하지 않는다. `build/web-review/upstream-results.json`에서 독립 실행 로그·원본 tree·시험 코드 해시에 연결한다. 전체 행동은 계속 0/12, 사람 평가는 미실시다.

추가 [브라우저 기록](upstream-tests/README.md)은 전후 12개 UI 조건과 6개 원본 클릭에서 18개 상태·배치 관찰을 남겼다. 특정 1280 × 1000 브라우저의 390 × 650 앱 안에서 버튼 중앙의 가림 여부와 클릭 후 복귀를 확인했다. `check:browser-recording`은 고정 기록을 현재 모델과 대조하며 브라우저를 재실행하지 않는다. 보기 모드 버튼 생성 변화뿐 아니라, 편집 모드·복귀 버튼만 활성 조건의 버튼 위치가 80px 아래로 바뀌는 결과도 확인했다. 후자는 현재 객체 전달 모델이 설명하지 못하는 배치 변화다. `build/web-review/browser-comparison.md`에 이 차이를 함께 표시한다.

`test:destructuring`은 기존 고정 원본의 Jitsi `isLiveStreamingButtonVisible`·`isRecordingSharingEnabled` 본문을 532개 입력에서 원본 JS 실행 및 독립 기대값과 대조한다. 미지원 입력 6개와 CLI 재실행 2개도 검사한다. 두 선언은 해당 커밋 전후에 동일함을 별도로 확인했으며, **변경 탐지 성공 사례로 세지 않는다.** 결과는 `build/web-review/destructuring-results.json`과 함수별 실행 설명에 남는다.

`corpus:inventory`는 전체 12개 원본 커밋의 변경 파일 목록을 별도로 재검사한다. 사례별 변경 파일 발생은 총 55개이고 기존 선택에 들어간 변경 파일은 26개, 선택 밖은 29개다. 동일 파일이 다른 사례에서 다시 바뀌면 별도 발생으로 센다. 선택 밖에는 테스트·문서 외에도 CSS·다른 UI·서버 코드가 있다. `change-inventory.lock.json`에 전후 tree·파일 object ID·추가/삭제 줄 수를 결합했으며 기존 선택과 82개 blob을 덮어쓰지 않았다. `build/web-review/change-inventory.md`에 전체 목록을 표시하고, 부분 비교의 `changeScope`에는 그 비교에서 다루지 않은 변경 파일을 기록한다. 이 파일 수는 의미 분석 성공률이 아니다.

`index-function-result --file 원본.tsx --function 함수이름`은 한 원본 파일에서 직접 함수 호출을 선택하고, 결과를 받는 const 또는 객체 분해 변수와 이후 사용을 연결한다. 같은 이름의 다른 변수는 제외하고 별칭·다른 함수 캡처·선택 밖 호출을 드러낸다. 외부 호출 인자 속성의 spread·계산 키·중복 키는 덮어쓰기 불확실성으로 남기며 `__proto__`의 prototype 설정을 일반 속성으로 분류하지 않는다. 산출 모드는 `function-result-bindings`이고 `explain`으로 원본 연결을 읽는다. `run`·실행 비교 대상으로 사용하면 거부한다.

`test:result-links`는 Actual 원본의 `resolveStartingSettings` 호출에서 날짜·잔액 결과 두 바인딩과 다섯 `.mutate` 호출의 인자 속성 10곳을 확인한다. 동적 계정 키의 입력 식과 함수 매개변수 위치도 연결하지만 호출의 도달·실행·서버 반영을 증명하지 않는다. 결과는 `build/web-review/result-link-results.json`, 원본 링크가 있는 설명은 `build/web-review/result-links/actual-starting-settings-arguments/source-links.md`에 생성한다. 함수 본문의 실행 검증과 이 소스 색인은 서로 다른 증거다.

소스 색인은 각 호출의 상위 if·삼항·단락 분기와 같은 함수의 선행 문장도 연결한다. Actual 사례에서는 `externalAccountIndex === -1` 분기의 선행 return 한 곳과 서비스별 다섯 분기 경로를 확인한다. return 조건을 나중 시점의 조건으로 대입하거나 반복된 속성 읽기를 같은 값으로 합치지 않는다. 콜백 경계에서 분기 상속을 멈추며 반복·try/catch/finally·switch·선택적 호출·클래스 필드는 별도 경계로 표시한다. 완전한 제어 흐름 그래프나 도달 증명이 아니며, 반복 문맥의 직렬화는 8 MiB에서 거부한다.

같은 색인에 `explain --file 연결.json --inputs 함수입력.json`을 사용하면 동일 원본의 순수 함수 본문과 결과 바인딩을 실행하고 사용 위치를 함께 보여준다. 입력은 호출 인수 식의 자동 계산값이 아니라 **함수 매개변수의 명시적 입력**이다. 결과 객체를 직렬화한 뒤 다시 읽지 않고 원래 IR에 분해 읽기를 연결하므로 생성 객체의 미확인 prototype과 null 분해 오류가 유지된다. 객체 값은 바인딩 시점의 구성값이며 나중 요청의 값으로 단정하지 않는다. `--json`에는 전체 입력·실행 기록·소스 색인이 포함된다. 입력 없는 `explain`은 소스 연결만 보여주며 색인의 `run`은 계속 거부한다.

이 결합 보기의 Actual 예시와 입력은 같은 출력 폴더의 `preview.md`, `preview-inputs.json`에 생성한다. `test:result-links`는 원래 함수와 결과 선언을 계정 하나가 들어 있는 레코드로 실행한 8개 예시와 결과 바인딩을 대조한다. 이 수치는 원본 요청 실행이나 전체 앱 검증으로 세지 않는다. 예를 들어 공백을 포함한 비어 있지 않은 날짜는 원문 그대로 남고 잔액 0도 유지된다. 결합 보기는 기존 16개 사람 평가 자료에 자동으로 추가하지 않았다.

`explain --file 연결.json --caller-inputs 호출입력.json`은 호출 지점의 식별자 스냅샷을 받아 **원래 인수 식 → 선택된 함수 본문 → 즉시 결과 바인딩**을 같은 IR로 연결한다. 두 입력 경계를 섞지 않도록 `--inputs`와 함께 사용할 수 없다. 인수 0~64개가 매개변수와 정확히 대응해야 하며, 직접 호출 밖 함수 참조(별칭·대입 등)가 있으면 거부한다. 지원 식과 일반 레코드 생성만 인수에서 계산하고 동적 함수 호출·호출 인수 spread·배열은 거부한다. 모든 인수를 왼쪽부터 한 번씩 계산한 뒤 매개변수 구조 분해를 진행하므로 사용하지 않는 인수의 오류도 사라지지 않는다. 결합 IR의 노드 수 65,536·깊이 128 제한을 적용한다.

Actual의 `customStartingDates[chosenExternalAccountId]`를 포함한 추가 8개 입력을 원래 함수·결과 선언의 네이티브 실행과 대조하고, 문자열이 아닌 키 3개를 미지원으로 확인한다. 결과는 `caller-preview.md`, `caller-preview.json`, `caller-inputs.json`에 생성한다. 예시 두 계정 중 어느 설정을 꺼내 날짜·잔액으로 계산했는지 실행 기록과 원본 위치로 이어진다. `customStartingDates` 등의 값 레코드 계약과 실제 함수 바인딩의 일치는 여전히 가정이다. callback의 도달·외부 요청 인자 전체·서버 반영·전체 앱 동작은 검증하지 않는다.

`lift-const-bindings --file 원본.tsx --start-line 시작 --end-line 끝 --outputs 변수1,변수2`는 한 블록의 연속된 const 선언을 읽고 끝에서 선택 변수 값을 관찰한다. 시작·끝은 각각 첫째·마지막 **문장의 시작 줄**이다. 단순 const 1~64개, 지원 식·일반 레코드 생성·표준 문자열 trim만 허용하고, 중간의 미지원 문장이나 사용하지 않는 초기화를 생략하지 않는다. 같은 구간의 초기화 전 읽기와 뒤에 선언된 지역 값의 대입도 거부한다. 객체 구조 분해를 받는 const 구간은 아직 지원하지 않는다.

`outputSources`에는 선택한 관찰 변수의 선언과 같은 원본의 심볼 참조를 별도로 담는다. 동일 이름의 다른 변수·타입 참조·콜백 캡처·직접 JSX 속성 사용을 구분한다. 변수당 2,048곳, 전체 4,096곳의 표시 제한과 생략 개수를 기록한다. 이는 원본 탐색 색인이며 구간 계산값이 이후에도 유지되거나 참조 위치가 실제로 실행된다는 뜻은 아니다. 구간이 오류로 끝나도 소스에 있는 선언·참조는 색인에 남는다.

`explain --file const분석.json --inputs 입력.json --props-index 속성색인.json`은 원본 내용 해시와 JSX·식별자 위치가 일치하는 직접 참조를 자식 매개변수·사용 식까지 이어서 보여준다. 두 분석의 전체 원본과 프로젝트 설정을 각각 재검사한다. 선택 const를 변환한 식이나 다른 이름의 변수로 전달하면 임의로 연결하지 않는다. 기본값·다른 함수 캡처·hook 인자도 실행 결과로 치환하지 않고 원본 식과 경계를 표시한다. JSON 출력에서는 `observation`과 `outputPropLinks`가 별개이며, `run`은 이 소스 연결 옵션을 받지 않는다.

`read --file const분석.json --props-index 속성색인.json`은 같은 소스 연결을 입력 없는 계산 구조 보기 뒤에 붙인다. 가능한 분기·목록 계산을 읽은 뒤 자식 파일의 사용처를 한 문서에서 따라갈 수 있다. JSON에는 `outputPropLinks`가 있지만 입력 실행의 `observation`은 없다. 자식 hook·기본값·실제 React 전달을 계산했다고 표시하지 않으며, 자식 원본이 달라지면 `explain`과 마찬가지로 다시 분석해야 한다.

`test:output-props`는 `test:arrays`와 `test:props` 이후에 실행한다. Actual의 전후 거래 선택 const와 TransactionListWithBalances의 속성 색인을 연결해 각 버전의 자식 참조 세 곳을 확인한다. `useSelected('transactions', [...transactions], [])`, DisplayPayeeProvider.transactions, TransactionList.transactions의 소스 사용이며 이 세 곳의 실행을 검증한 수치가 아니다. 결합 결과와 설명은 `build/web-review/output-props/actual-transaction-selection-destinations/`에 저장하고 원본 재검사 8회(계산 구조 보기 4회 포함)를 기록한다. 두 보기의 소스 연결이 같은지도 확인하며, 보기 수를 연결한 사용처 수로 중복 집계하지 않는다. 전체 로컬 검증 명령은 이 선후 관계를 지킨다.

`lift-call-bindings --file 원본.tsx --function 함수이름`은 원래 인수 식·선택 함수 본문·즉시 결과 바인딩을 실행 모델로 저장한다. 소스 색인 명령과 달리 이 모델은 명시한 입력으로 `run`·`explain`할 수 있다. 구간 모델과 호출 모델의 **관찰 변수 이름과 순서가 같을 때만** CLI `compare`가 서로 다른 두 모드의 비교를 허용한다. 결과 레코드는 앱에 새로 만드는 객체가 아니라 선택 변수 값을 담는 보고용 관찰이다. 원본·선택 줄·출력 이름·실행 모델을 다시 추출해 편집되거나 오래된 산출물을 거부한다.

`test:bindings`는 Actual의 변경 전 311~316행 시작 const 세 선언과 변경 후 `resolveStartingSettings` 호출을 비교한다. 고정한 122개 입력 조합에서 startingDate·startingBalance 또는 TypeError 관찰이 모두 같았고, 변경 전후 원본 실행 244회와 일치했다. 그중 오류 관찰 8회는 전체 실행 244회에 포함되며, 별도 미지원 입력은 6회다. 이 부분은 함수 추출에 따른 구조 변경으로 확인됐지만 커밋의 다른 UI 변경이나 다섯 요청의 실행까지 동일하다는 뜻은 아니다. `build/web-review/binding-comparisons/actual-starting-settings-refactor/comparison.md`와 `binding-comparison-results.json`에서 분모·원본·입력·미확인 범위를 확인할 수 있다.

### 표준 배열에서 거래 목록 선택 비교

`lift-const-bindings`에 `--array-profile dense-standard-array-1`을 명시하면 빈칸 없는 배열 리터럴, 자체 `length`·존재하는 문자열 인덱스 읽기, 순수한 `filter`, 배열 인수만 받는 `concat`을 사용할 수 있다. 프로필은 분석 대상과 IR에 결합하며 CLI 재검사에서 가정의 변경도 확인한다. 다른 모드의 배열 지원으로 확대하지 않는다. 입력과 출력 배열은 `{ "$array": [...] }`로 인코딩하고 원소 순서를 보존한다. `undefined` 원소와 빈칸은 다르며 후자는 거부한다. 길이는 배열당 16,384개 이하이며 전개 크기·실행 단계·기록 제한을 그대로 적용한다.

이 프로필은 표준 Array·Object 프로토타입과 filter·concat·constructor/species·isConcatSpreadable을 변경하지 않았다는 가정이다. 배열 하위 클래스·추가 자체 속성·접근자·심볼·Proxy·객체 별칭은 제외한다. 실제 입력의 Proxy 여부나 외부 코드가 프로토타입을 바꾸지 않았다는 사실을 타입으로 증명한 것은 아니다. 인코더는 확인 가능한 자체 속성·직접 프로토타입 형태를 검사하고, JSON 값 모델 밖의 실행 환경은 가정으로 표시한다.

filter 콜백은 단순 매개변수 하나와 식 본문을 가진 동기 화살표 함수로 제한한다. 본문에서 지원하는 순수 식만 허용하며, 원소를 앞에서부터 검사해 참으로 취급되는 원소를 순서대로 보존한다. 중첩된 콜백의 같은 이름과 외부 스냅샷 참조를 구별한다. concat은 모든 인수를 평가한 뒤 앞 목록과 인수 목록을 얕게 이어 붙이며 중복 제거·정렬을 하지 않는다. 두 연산은 독립 실행기의 반복으로 구현했다. 객체 원소를 재인코딩해 미확인 프로토타입 경계를 없애지 않는다. 의미 기준은 [ECMAScript 2024 filter](https://tc39.es/ecma262/2024/multipage/indexed-collections.html#sec-array.prototype.filter)와 [concat](https://tc39.es/ecma262/2024/multipage/indexed-collections.html#sec-array.prototype.concat)이며 일반 객체·희소 배열에 대한 전체 명세를 구현했다는 뜻은 아니다.

`test:arrays`는 Actual 모바일 필터 변경의 `transactionsToDisplay` 원본 const를 전후 122행·162행에서 그대로 추출한다. 고정한 160개 입력 조합에서 목록의 모든 관찰 필드와 순서를 비교했고 34개가 달랐다. 원본 실행 320회와 별도 오류 입력 24회가 독립 실행기와 일치했다. 오류 입력에서 TypeError는 9회이며 실제 사용자가 그 입력에 도달한다는 주장은 아니다. 별도 미지원 검사 16회와 CLI 재검사 5회(계산 구조 보기 2회 포함)를 남긴다. 비불리언 is_child 등도 JavaScript 의미 경계용 입력으로 명시하며 실제 거래 타입의 유효성 증거로 쓰지 않는다.

예시에서 검색을 끄고 필터를 켜면 선택 ID 순서는 `[preview, z, a]`에서 `[z, b, a]`로 바뀐다. 이 표시는 예시를 읽기 위한 것이고 ID만 비교하지 않는다. `build/web-review/arrays/actual-filter-transaction-selection/`에 원본 구간·프로필·입력·전후 실행 설명·비교를, `array-results.json`에 집계를 남긴다. 조회 결과의 생성·React 상태·실제 화면 행과 전체 변경은 아직 별도다.

목록 변경 보기는 원소 전체 관찰값을 대조해 이전 목록에서 제외한 위치와 이후 목록에 추가한 위치를 구분한다. ID가 같아도 다른 필드 값이 달라지면 같은 원소로 묶지 않는다. 중복된 같은 값은 가능한 정렬 중 하나를 택하며 객체의 이동·동일성을 추론하지 않는다. 각 수정 목록을 이전 배열에 적용해 이후 관찰 배열의 모든 값과 순서가 복원됐는지 별도로 검사한 경우에만 완성된 변경 보기로 표시한다. Actual의 변경 조합 34개 모두에 대해 이 재검사를 수행하고 `observation-deltas.json`에 남긴다. 기본 256개 원소·64개 수정·작업량·용량 제한을 넘거나 값이 미지원이면 전체 관찰값 비교로 돌아가며 일부 수정만 완성본처럼 제시하지 않는다. 이 수정은 관찰 데이터의 차이이며 소스 코드 패치가 아니다.

## 객체 식과 속성 생략

`lift-record --file 원본.tsx --line 시작줄 [--column 시작열]`은 원본의 객체 리터럴 하나를 수정 없이 추출한다. 같은 줄에 여러 객체가 있으면 열까지 지정해야 한다. `run`·`explain`·`compare`는 다른 실행 산출물과 같이 원본·선택자·IR·엔진을 재확인한다. 식별자는 그 식의 평가 지점에 제공한 입력이며, 둘러싼 콜백이나 앞선 호출 인수를 실행했다고 하지 않는다. `undefined`의 지역 선언이 있으면 입력으로 유지한다.

객체 식·함수 본문·const 구간·호출 인수의 객체 생성에서 `{ ...draft, date: replacement }` 같은 복사를 지원한다. spread는 열거 가능한 자체 문자열 속성을 얕게 복사하고, 없는 속성을 만들지 않는다. 뒤에 적힌 속성이 앞 값을 덮어써도 앞선 계산·오류를 생략하지 않는다. 복사 대상은 값 레코드와 null·undefined·숫자·불리언으로 제한한다. 문자열·배열·불투명 객체·JSX·심볼·getter·Proxy는 지원하지 않는다. 객체 복사 속성마다 실행 단계 예산을 사용하고 기록은 512개로 제한한다. 중첩된 생성 객체를 복사해도 기존의 미확인 prototype 경계를 유지한다. 의미 근거는 [CopyDataProperties](https://tc39.es/ecma262/multipage/abstract-operations.html#sec-copydataproperties)와 [객체 속성의 평가 순서](https://tc39.es/ecma262/multipage/ecmascript-language-expressions.html#sec-object-initializer-runtime-semantics-propertydefinitionevaluation)다.

`test:records`는 고정한 Actual의 전후 날짜·잔액 수정용 객체 식 8곳과 AmountInput.value 4곳을 원본 실행 496회와 대조한다. 이 중 TypeError 20회는 496회에 포함하고, 별도 미지원 검사는 24회다. 같은 입력에서 전후 객체 식은 동일하지만 value 식은 amount가 null·undefined일 때 0을 대신 전달한다. 날짜 수정용 객체는 없는 amount를 만들지 않고, 잔액을 지정하는 객체는 amount를 생성한다. `build/web-review/records/actual-starting-settings-records/review.md`는 이 독립 관찰을 나란히 보여준다. 입력 이벤트 레코드는 명시한 스냅샷이며 실제 DOM Event, 상태 전이, 요청·서버 실행을 검증한 수치가 아니다. 전체 행동 0/12와 참가자 0명은 유지한다.

읽기 보기는 정상 완료 시 문자열임을 IR에서 확인할 수 있는 일부 식에 `normalCompletionType`과 근거 규칙을 남긴다. 문자열 리터럴·표준 trim·typeof 결과와 이 값을 보존하는 저장·두 갈래·논리 연산만 대상으로 한다. 이 근거가 있을 때만 `!값`을 ‘빈 문자열인지’로 표현한다. TypeScript의 매개변수 타입 선언이나 실제 입력값을 추측해서 적용하지 않는다. 정상 완료의 값 종류에 대한 정보일 뿐이며, 선행 오류·미지원 결과·실제 도달 여부는 그대로 남는다. Actual 이름 변경의 `!trimmed`에 한 규칙을 적용했고, 기존 IR을 변경하거나 새 언어 문법을 실행한 것은 아니다.

`lift-call-arguments --file 코드.tsx --callee renameTag --line 69`는 호출 진입과 같은 선행 구간을 인수 식까지 연결한다. 인수는 spread 없이 32개까지, 기존 순수 식·원시 문자열 trim·toLowerCase·값 레코드 범위에서 해석한다. 배열 식과 다른 호출은 지원하지 않는다. 보고용 레코드의 `argument1` 등은 인수 위치별 값이고 `stage`는 `early-return` 또는 `arguments-ready`다. 준비 완료 상태는 모든 인수 계산 뒤에만 기록하며 중간 오류가 나면 뒤 인수를 계산하지 않는다. callee 식별자 값 읽기의 정상 완료는 가정이고, 이 읽기는 실제 JavaScript에서 인수보다 먼저 일어난다.

`test:call-arguments`는 먼저 생성한 `test:call-entries`의 해시가 일치하는 원본 기록을 재사용한다. Actual의 기존 117개 입력에서 인수 준비 37개·조기 반환 50개·TypeError 30개가 일치했다. 이를 새 원본 실행 117회로 집계하지 않는다. 인수 getter·호출 불가능한 값·callee 오류의 경계 사례 3개와 미지원 프로필 3개도 유지한다. 출력은 `build/web-review/call-arguments/actual-tag-rename-validation/` 및 `call-argument-results.json`이다. CLI는 두 호출 모델을 서로 비교하지 않으며 같은 모델·같은 호출 이름의 전후 결과만 비교한다.

원시 문자열의 `toLowerCase()`와 `trim()`은 const 구간·순수 함수·호출 선행 구간·순수 인수에서 해석한다. 연속 문자열 처리는 입력을 읽는 순서부터 한 문장으로 표시하고 각 연산의 원본 위치는 읽기 JSON에 유지한다. 소문자 변환은 [ECMAScript의 유니코드 기본 변환](https://tc39.es/ecma262/multipage/text-processing.html#sec-string.prototype.tolowercase)을 따르는 호스트 표준 메서드를 사용하며 언어권별 변환·객체 수신자·메서드 변경은 지원하지 않는다. 출력이 길어지는 경우에도 작업량·문자열 길이 제한을 검사한다. 엔진 식별 해시는 소스·의존성 잠금과 함께 Node·V8·Unicode·ICU·플랫폼·아키텍처를 포함하므로 다른 실행 환경에서 이전 분석물을 그대로 재사용할 수 없다.

`test:color-normalization`은 고정 Excalidraw의 `ColorInput.tsx` 전후 42행·43행의 첫 const를 원본 그대로 실행한다. 입력 98개·전후 원본 실행 196회가 글 IR과 일치했고, 양끝 공백 제거로 64개 관찰값이 달라졌다. null·undefined의 TypeError 4회는 196회에 포함한다. 미지원 입력 6회·표준 메서드 변경 반례 2회는 별도 검사다. 결과는 `build/web-review/color-normalization/excalidraw-color-normalization/`과 `color-normalization-results.json`에 남긴다. `normalizeInputColor`, 정규식, 상태 변경, 화면·저장 동작을 실행한 결과가 아니며 전체 행동 0/12와 참가자 0명을 유지한다.

`discover --file`은 줄번호를 먼저 정하지 않고 const 문장·명시된 JSX 속성·함수 블록 마지막의 직접 호출을 찾는다. 각 후보를 기존 추출기로 실제 해석하고 `lowered`·`refused`·`not-checked`로 나눈다. `--kind`는 `all`·`const`·`jsx-attribute`·`call-entry`·`call-arguments` 중 하나다. 기본 32개, 최대 128개를 검사하고 `--offset`으로 다음 후보부터 이어 간다. 이전 페이지의 결과를 이번 페이지가 검사한 것으로 합치지 않는다. 파일당 후보 4096개·AST 노드 100000개·깊이 128·누적 원본 재해석 16 MiB 제한이 있으며, 작업량 때문에 건너뛴 후보도 지원 여부 미확인으로 남긴다.

JSON의 `lift.command`·`lift.file`·`lift.target`은 재추출할 대상을 구조화해 제공한다. 후보 목록은 실행 모델이 아니므로 `read`·`run`에 직접 넣지 않는다. 같은 줄에 같은 선택 조건의 대상이 여럿이면 임의로 고르지 않는다. 거부 위치도 내부 가상 파일 대신 원본 위치를 가리킨다. `test:discovery`는 고정한 Excalidraw·Actual·Jitsi 파일 3개에서 10페이지의 후보 264개를 중복 없이 검사하고 CLI 재검사 15회를 수행한다. 명시적 선택 명령과 `lift-candidate`의 재추출 결과가 같은지도 대조한다. 서로 다른 소스 범위는 256곳이고 IR 추출 170개·거부 94개이며, IR 추출 중 선행 계산 없는 호출 진입 5개를 별도로 기록한다. 정적 JSX 문자열도 포함한 구문 후보 수이며 실제 행동 처리율·원본 실행·사람 검토 성과로 사용하지 않는다. 이 검사의 원본 실행은 0회다.

`lift-candidate --file 후보페이지.json --candidate 번호`는 저장한 페이지와 현재 원본을 다시 탐색해 모두 일치할 때 해당 후보를 일반 분석 결과로 추출한다. 변경 탐색 페이지에서는 `--revision before` 또는 `--revision after`를 반드시 지정하며 두 원본과 저장된 `patch.file`도 다시 읽는다. 검사한 페이지의 `lowered` 후보만 추출할 수 있다. 미검사 후보는 해당 번호부터 다시 탐색해야 하며 엔진·원본·패치·선택 조건·후보 결과가 달라지면 거부한다. 파일은 UTF-8이고 원본 2 MiB·패치와 목록 16 MiB 제한을 적용한다. `pages.json`의 전체 배열 대신 한 페이지 객체를 입력한다. 이 재검사는 원본 실행이나 동작 보장이 아니며, 출력은 기존 `read`·`run`·`compare`에서 같은 계약으로 사용한다. 실제 사례의 `anchor-page.json`·`anchor.json`·`anchor-reading.md`는 탐색→추출→읽기 경로를 보여준다.

`discover-change`은 두 원본 파일과 단일 파일 Git unified patch를 받아 변경 후 전체 내용을 정확히 복원한 뒤 후보에 변경 행을 연결한다. 후보 위치, 추출기가 살펴본 선택 구문, IR에 포함된 계산 구간의 교차를 따로 기록한다. 마지막 호출 줄이 그대로여도 앞선 조건이 바뀌면 선행 계산 구간에 연결된다. 호출 인수의 변경은 호출 진입 모델에서 계산한 것으로 표시하지 않는다. JSX의 다른 행에 spread가 추가되어 추출이 거부되면 계산 구간을 빈 것으로 간주하지 않고 `null`로 남긴다. 같은 행의 주석만 바뀌어도 소스 교차가 발생할 수 있으므로 교차를 의미 변화로 해석하지 않는다.

이 명령의 전후 후보 번호는 독립적이다. `--before-offset`·`--after-offset`으로 각 파일의 다음 페이지 또는 특정 후보부터 검사한다. 표는 선택 구문과 변경 행이 교차하는 후보 40개까지 보여주며 JSON에는 전체 목록이 있다. 연결은 최대 65536개까지 허용하고 초과하면 부분 목록을 완성본으로 반환하지 않는다. 일반 CLI는 Git 커밋·패치 헤더 경로·파일 모드의 동일성을 확인하지 않으며, 전후 후보를 같은 행동으로 자동 대응시키거나 실행 결과를 비교하지 않는다. `test:change-discovery`는 별도로 고정 Git 커밋의 blob까지 대조해 실제 변경 3개의 원본 6개·전후 후보 510개를 10페이지로 검사하고, 변경 행에 집중하는 선택과 후보 재추출·읽기까지 포함해 CLI 재검사 18회를 수행한다. 원본 프로그램 실행은 0회이며 `build/web-review/change-discovery/`에 근거를 남긴다.

`--focus changed-lines`는 변경 행과 선택 구문이 교차하는 후보에 검사 한도를 사용한다. 기본 `--focus all`의 후보 번호를 유지하고, 범위 밖 후보는 `inFocus: false`·`not-checked`로 남긴다. 다음 페이지는 중간의 범위 밖 후보를 지나 다음 검사 대상 번호에서 이어진다. 고정 사례에서는 검사 대상이 510개에서 92개가 됐으며, 이 92개의 결과가 전체 검사에서 얻은 해당 후보 결과와 정확히 일치했다. 418개는 미검사로 남고 간접 의존성의 영향도 판단하지 않는다. 이는 검사할 후보 수의 차이이며 실행 속도나 사람 검토 시간의 개선을 측정한 결과가 아니다.

## 다음 구현

1. 순수 프로젝트에서 결합한 설정·모듈 색인·실행 해석을 실제 사례의 선택 지점으로 적용하고, 미지원 문맥을 분리해 지역 정의·호출·도달 조건을 연결한다.
2. JSX 분기를 포함하는 실행 표현과 원본 위치 연결을 만든다. 이름만 바꾼 한국어 코드와 비교해 이점이 있는지 시험한다.
3. 고정 사례의 조건·미지원·실행 차이를 재현 가능한 검토 과제로 만든다. [파일럿 초안](evaluation/protocol.md)에 네 부분 과제와 네 비교 조건을 정리했다. `prepare:pilot`은 16개 비교 자료와 8개 미배정 슬롯을 만들며, 과제×조건·과제×순서를 각각 두 번씩 배정한다. `npm.cmd run practice`로 [예행 검토 화면](evaluation/viewer/README.md)을 열어 자료·원본·시간·답변 내보내기를 점검할 수 있다. 실제 참가자는 0명이고 사람 예행 검토·최종 채점표·본 실험의 시간 측정 운영 검증이 남아 있다.
4. 사람 평가를 바탕으로 상태·Effect·비동기 및 TypeScript 생성·편집 왕복 확장을 결정한다.

한국어 출력의 문법·표현은 실험 대상이다. 현재 모양을 최종 언어 설계로 고정하지 않는다.
