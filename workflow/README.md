# 워크플로 편집 프로젝트

이 디렉터리는 `jazz-piano-coach/` monorepo의 워크플로 개발 영역입니다. 여기서 세션을
열면 코칭 규칙·커리큘럼·프로그램을 편집하는 역할로 시작합니다. 실제 일일 연습은
`../practice`에서 진행하며 Git 저장소는 루트 하나를 공유합니다.

## 개발과 발행

```sh
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python review.py validate-curriculum
uv run python review.py status
```

`status`와 `validate`는 실제 기록을 읽기만 합니다. 개발 중 과제 발급·결과 기록은
테스트의 임시 디렉터리를 사용합니다. 개발 보고서는 별도 위치에 생성합니다.

```sh
uv run python review.py report --output build/preview.html
```

소스 수정은 연습용에 즉시 반영되지 않습니다. 코드, curriculum, COACH 중 하나라도
발행 후 변경했다면 `curriculum.yaml`의 version과 `pyproject.toml`의 version을
함께 올리고 테스트합니다. 새 curriculum에서도 과거 과제는 발급 당시 기준으로
평가됩니다. 대표 목표는 현재 기준과 자료/연주 조건이 호환되는 성공만 집계합니다.

```sh
uv run python publish.py --activate
```

같은 버전의 다른 내용은 덮어쓰지 않습니다. 발행본은 `../practice/releases/`에
복사되고 `active-version`으로 선택됩니다. 미완료 과제가 있으면 활성화가 거부됩니다.
활성화 없이 `publish.py`만 실행하면 설치만 합니다. 발행 후 연습 프로젝트에서
`./jazz report`를 실행해 보고서를 갱신합니다.

Python 의존성은 uv.lock으로 고정합니다. 런타임 파일의 해시는 실행 때 확인합니다.
Git은 상위 `jazz-piano-coach/` 루트에서 관리합니다.

## 과제와 결과 CLI

하루에 여러 과제를 순서대로 진행할 수 있습니다. 진행 중인 과제는 한 번에 하나이며,
결과를 기록하거나 취소하면 같은 날 다음 과제를 발급합니다. 기본 30분은 하루 전체
예산입니다. `status`의 `today`에 오늘 과제 수, 알려진 시간, 시간 미확인 건수,
기록 기준 남은 시간이 나옵니다. 시간이 빠진 결과가 있으면 남은 시간은 `null`이며,
알려진 시간만으로 예산에 도달하면 0입니다. 시간 예산은 추가 연습을 차단하지 않습니다.

쉬운 과제는 통과 기준을 짧게 확인한 뒤 바로 넘어갑니다. `difficulty: easy`만으로는
통과하지 않습니다. 어렵다고 보고한 미통과 과제(`difficulty: hard`)와 취소한 과제는
같은 항목·키의 오늘 추천에서 보류합니다. `suggest.deferred_today`에 원문과 과제 ID를
남기며, 다른 후보도 선행 조건을 충족해야 합니다. 후보가 없으면 `action: pause`로
마무리 또는 조건 조정을 안내합니다. 다음 날 다시 후보가 되며, 원하면 같은 날에도
직접 재발급할 수 있습니다. 새 결과는 이전 보류보다 우선합니다.

아직 하지 않은 과제는 `cancel`, 조금이라도 해본 과제는 `record`로 종료합니다.
취소 사유는 사용자 원문을 그대로 남깁니다. 통과 기준, 과거 원문, 발급 조건은 유지하며
당일 여러 항목의 통과를 후일 재현이나 시도하지 않은 항목의 성공으로 확대하지 않습니다.

다음 명령은 **연습 프로젝트에서 사용자가 실제 연습을 시작할 때** 사용합니다.
이 README를 읽었다는 이유만으로 실제 로그에 실행하지 마세요.

```sh
./jazz assign E01 --key C --bpm 60 --reason '왼손 루트와 박 유지의 출발점 확인'
./jazz record T-발급된ID --input /tmp/jazz-result.json
./jazz correct T-발급된ID --input /tmp/jazz-corrected-result.json
./jazz cancel T-발급된ID --reason '이번 과제는 연습하지 않음'
```

결과 JSON의 예시 형식입니다. 이 값들은 사용자 실적이 아닙니다. 사용자가 명시한
정보만 채웁니다. 모르는 숫자/검사 결과는 생략하거나 null로 남깁니다.

```json
{
  "practice_date": "YYYY-MM-DD",
  "followed_target": false,
  "actual": {"key": "C", "bpm": 50, "arrangement": "right-melody-only"},
  "checks": {"notes_correct": true, "steady_pulse": null, "no_stops": false},
  "clean_runs": null,
  "actual_minutes": 20,
  "difficulty": "hard",
  "raw_note": "사용자 원문을 여기에 그대로 저장",
  "hypothesis": "코치 가설은 별도 문자열. 보고 내용으로 확정하지 않음."
}
```

`followed_target: true`는 사용자가 지정 조건을 그대로 지켰다고 말했을 때만 사용합니다.
조건을 복사해도 검사 결과와 성공 횟수까지 자동으로 true가 되지 않습니다.
`correct`에는 교체할 결과 전체를 넣습니다. 이전 사건은 CSV에 보존됩니다.

## CSV 구조

`practice/practice.csv` 한 곳에 사건을 추가합니다. `task_id`로 과제 발급과 결과를
연결하고 `event_id`로 각 사건을 구분합니다. 기록 중 파일 잠금을 사용합니다.

| 주요 열 | 의미 |
| --- | --- |
| event_type | assigned / reported / cancelled / corrected |
| target_json | 발급 당시 키·BPM·손·리듬·베이스·보이싱·멜로디·자료·통과 기준 |
| actual_json | 사용자가 실제 수행했다고 보고한 조건 |
| checks_json | 음/박/무중단 여부. true / false / null |
| clean_runs | 조건을 지킨 연속 성공 횟수. 미확인은 빈 값 |
| raw_note | 사용자 원문. 쉼표와 줄바꿈도 보존 |
| hypothesis | 코치의 해석. 원문과 분리 |
| supersedes | 정정된 이전 결과 사건의 ID |

수치는 스크립트로 계산합니다. LLM이 임의의 '실력 73점' 같은 값을 저장하지 않습니다.
보고서는 원본을 수정하지 않으며 삭제 후 다시 생성할 수 있습니다.
