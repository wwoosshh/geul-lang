# 예행 채점 도구

**참가자 0명, 실제 채점·실험 미실시.** 이 도구는 사람의 채점 준비와 기록을 점검한다. 자유 서술을 AI나 문자열 일치로 자동 채점하지 않는다. [rubric.json](rubric.json)은 사람 검토가 필요한 초안이며, 네 과제 각각에 조건·전후 값·예외·보장 범위의 0·1·2점 기준을 담았다.

`prepare:pilot`은 `build/web-pilot/private/rubric.json`·`rubric.md`를 생성하고 원본 기준과 생성 도구의 해시를 manifest에 결합한다. 참가자용 자료·네 조건의 추가 정보는 바꾸지 않는다. 정답 기준은 원본 식의 값 방향을 따른다. 예를 들어 시작 잔액 과제의 **입력 속성**은 undefined/null→0이며, 해당 커밋의 **서버 전송**에 대한 설명으로 뒤집어 쓰지 않는다.

예행 화면에서 내보낸 응답 JSON으로 다음을 실행한다.

```powershell
npm.cmd run score:practice -- prepare --response C:/path/to/practice-response.json --id practice-001
```

준비한 현재 자료와 응답의 materialSha256이 일치해야 한다. 출력은 `build/web-score-practice/run-*`의 새 폴더에 저장하며 이전 응답을 덮어쓰지 않는다. 실제 참가자가 있는 응답이나 본 실험 모드는 이 도구의 입력으로 받지 않는다.

채점자에게 `score-sheet.json`과 과제별 채점 기준만 제공한다. `private`에는 조건·시간·확신도·AI 사용 정보와 원본 응답을 보존하므로 채점 완료 전 가린다. 채점 양식에는 조건 메타데이터를 복사하지 않지만 자유 서술은 수정하지 않는다. 응답 내용으로 조건을 추측할 수 있다는 한계는 남는다. 준비한 사람이 같은 사람으로 채점한다면 독립적인 눈가림이 확보됐다고 하지 않는다.

사람이 각 항목의 `score`와 `reason`, `boundaryOverclaim`을 채운다. 범위 밖 단정이 있다고 판단하면 `boundaryEvidence`에 응답의 실제 구절을 인용한다. 프로그램은 인용이 응답에 존재하는지만 확인하며 해석이 올바른지 판정하지 않는다.

```powershell
npm.cmd run score:practice -- inspect --packet C:/geul/geul-lang/build/web-score-practice/run-EXAMPLE
```

미채점 항목은 null이다. 네 점수와 범위 밖 단정 여부가 모두 입력되기 전에는 합계도 null로 남긴다. 모두 입력되면 최대 8점의 합계만 계산하며 사람 점수의 정확성이나 채점자 간 일치도까지 검증했다고 하지 않는다. 원본 응답·과제 내용이 수정됐거나 고정한 원본 양식이 달라지면 거부한다.

`npm.cmd run test:scoring`은 합성 예행 응답 한 개로 준비·미완료·합계·변조 거부를 확인한다. 합성 점수나 테스트 횟수는 사람 참가자·검토 정확도·검토 시간 자료가 아니다. 결과와 거부 로그는 `build/web-review/scoring-results.json`에서 확인한다. 본 파일럿을 시작하려면 사람 예행 검토, 최종 기준 동결, 모집 및 중단·시간 측정 운영 검증이 여전히 필요하다.
