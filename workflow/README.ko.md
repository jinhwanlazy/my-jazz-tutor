# 워크플로 편집 프로젝트

[English](README.md) · [한국어 원문](README.ko.md)

이 디렉터리는 `my-jazz-tutor/` monorepo의 워크플로 개발 영역입니다. 여기서 세션을
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
함께 올리고 `uv lock` 후 테스트합니다. 새 curriculum에서도 과거 과제는 발급 당시 기준으로
평가됩니다. 대표 목표는 현재 기준과 자료/연주 조건이 호환되는 성공만 집계합니다.

검증한 소스를 Git에 커밋하고 버전 태그를 붙인 뒤 설치합니다. 다음은 `0.2.3` 태그가
가리키는 커밋을 선택하는 예입니다. 이후 버전은 새 태그를 만들고 기존 태그를 이동하지 않습니다.

```sh
uv run python publish.py --ref v0.2.3 --activate
```

버전 이력은 Git 커밋·태그에만 보관합니다. 실행 파일은 선택한 커밋의 `workflow/`에서
읽어 `../practice/.runtime/<commit>/`에 캐시하며 Git에 추가하지 않습니다. `--activate`는
로컬 `practice/runtime.json`에 전체 커밋 해시를 고정합니다. 미완료 과제가 있으면
다른 커밋의 활성화를 거부합니다. `--activate`를 생략하면 캐시만 준비합니다.

기본 ref는 `HEAD`이며 실행 소스에 미커밋 변경이 있으면 설치를 거부합니다. 이전 태그를
명시하면 작업 중인 소스와 독립적으로 그 Git 커밋을 설치할 수 있습니다. 새 작업 공간의
최초 기본값은 `practice/runtime-ref`입니다. 실행기 설치로 기본값이 바뀌어도 기존의
로컬 고정 커밋은 바뀌지 않습니다. 캐시를 삭제하면 다음 실행에서 같은 커밋을 복원합니다.
고정한 커밋을 로컬 Git에서 찾을 수 없으면 실행을 중단하며 개발 소스로 대체하지 않습니다.

기존 `practice/releases/` 복사본은 과거 Git 이력에 보존되어 있습니다. 이전 설치본의
파일과 일치하는 커밋을 `--ref`로 선택하면 같은 버전을 유지한 채 이관할 수 있습니다.
`active-version`은 구버전 코드 호환을 위한 로컬 파일이며 새 선택 기준은 `runtime.json`입니다.

Python 의존성은 uv.lock으로 고정합니다. 런타임 파일의 해시는 실행 때 확인합니다.
Git은 상위 `my-jazz-tutor/` 루트에서 관리합니다.
개인 CSV·프로필·MIDI·개선 메모·보고서·백업은 Git에서 제외합니다. 새로 clone했다면
[practice 초기 설정](../practice/README.ko.md)에 따라 로컬 `profile.json`을 준비한 뒤
실행기를 설치하거나 버전을 발행합니다. 실제 연습 데이터는 공유용 테스트에 복사하지 않습니다.

## 웹 연습실

0.2.0부터 과제 제시·연습·결과 입력·규칙 기반 피드백·기록 조회·정정을 브라우저에서
진행합니다. 외부 LLM API 키나 Node 런타임은 필요하지 않습니다. Python 표준
라이브러리 서버와 브라우저 Web Audio를 사용합니다. 자유 대화형 AI 코칭과 MIDI
음악 분석은 이번 범위에 포함하지 않습니다.

0.2.0 이상을 활성화한 뒤 저장소 루트에서 실행합니다. `uv`가 실행 환경을 준비하며,
인자가 없는 `jazz`는 `serve --open`을 실행합니다.

```sh
# 저장소 루트에서
uv run --project practice jazz
```

주소는 `http://127.0.0.1:8765`이며 다른 장치에서 접속할 수 없습니다. 포트를 이미
사용 중이면 `--port 8768`처럼 바꿉니다. 종료는 Ctrl+C입니다. 미완료 과제가 있어
0.2.0 활성화가 보류됐다면 기존 버전에서 해당 과제의 실제 결과를 기록하거나, 사용자가
연습하지 않았다고 확인한 경우 취소한 뒤 workflow에서 `uv run python publish.py --ref v0.2.3 --activate`를
실행합니다. 새 UI 설치를 위해 과제나 보고를 임의로 만들거나 없애지 않습니다.

- **연습실**: 추천 또는 선택한 과제로 시작합니다. 목표 BPM과 현재 메트로놈 BPM은
  구분합니다. BPM·음량을 조절하고 코드 패드를 선택적으로 켭니다. 재생과 패드는 같은
  박자를 사용하며 이어하기는 첫 마디에서 다시 시작합니다. 다른 탭으로 가면 재생이 멈춥니다.
- **종료와 기록**: 종료하면 입력을 저장하고 BPM·시간 후보를 채웁니다. 키·손·구간을
  지켰는지, 음·박·무중단·성공 횟수와 메모는 직접 확인합니다. 난이도가 쉬움이어도
  근거 없이 성공을 만들지 않습니다. 어려운 과제는 실제 시도 내용을 남기고 다음으로 갑니다.
- **스킵**: 아직 연습하지 않은 과제는 이유와 함께 오늘 추천에서 보류할 수 있습니다.
  다음 과제도 선행 조건을 지켜 선택합니다. 하루 과제 수 제한은 없습니다.
- **연습 기록·나의 진도**: 날짜·과제·키로 조회하고 원문과 발급/실제 조건을 비교합니다.
  정정하면 이전 보고도 남습니다. MIDI 원본과 세션 정보도 여기서 내려받습니다.

MIDI는 선택 기능입니다. 로컬 주소에서 Web MIDI를 지원하는 브라우저(예: Chrome)를
사용하고 **MIDI 입력 → 연결하기**에서 권한을 허용합니다. 기본은 연결된 모든 입력이며
장치를 따로 선택할 수 있습니다. 브라우저에서 전달하는 원본 bytes를 저장하고 SysEx
권한은 요청하지 않습니다. 권한이 없거나 장치가 없어도 나머지 기능은 사용할 수 있습니다.
지원 조건은 [MDN Web MIDI](https://developer.mozilla.org/en-US/docs/Web/API/Web_MIDI_API)를 참고하세요.

자동 입력의 의미는 다음과 같습니다.

- **BPM**은 마지막 음 입력 시점의 메트로놈 설정입니다. MIDI가 없으면 마지막 재생
  설정이며 실제 타건을 분석한 템포가 아닙니다.
- **MIDI 시간**은 첫 Note On부터 마지막 Note Off/서스테인 해제까지입니다. 앞뒤만
  제외하고 중간 쉼은 유지합니다. 원본을 잘라내지 않습니다. 음 종료 누락·장치 변경·
  입력 중단이 있으면 미확인으로 남깁니다.
- MIDI 시간을 구할 수 없으면 일시정지를 뺀 **재생 시간**을 제안합니다. 복구한 중단
  세션은 시간을 직접 입력합니다. 준비·회고 등을 포함한 실제 시간을 확인하고 수정하세요.

3초마다 IndexedDB에 먼저 저장하고 서버로 보냅니다. 서버 확인 전 청크는 브라우저에
남으며 저장 재시도 시 중복으로 추가되지 않습니다. 다시 접속하면 **연습 복구하기**로
미전송 입력을 저장합니다. 원래 사용하던 브라우저·주소·포트로 돌아와야 IndexedDB를
찾을 수 있습니다. 다른 연습 탭은 닫고 복구하세요. 마지막 체크포인트 이후 강제 종료된
구간은 복구를 보장하지 않습니다. 브라우저 저장 공간을 지우면 미전송 청크도 사라집니다.

개발 미리보기는 실제 practice 폴더에 연결할 수 없습니다.

```sh
# 저장소 루트에서
cd workflow
mkdir -p build/web-preview
uv run python review.py --practice-root build/web-preview serve --open --port 8768
```

개발 미리보기의 기록은 `build/web-preview/`에만 남고 Git에서 제외됩니다.

### uv 실행기 관리

`launcher/`가 `practice`용 uv 프로젝트와 진입점의 원본입니다. 변경 사항은 workflow에서
다음 명령으로 적용합니다.

```sh
uv lock --project launcher
uv run python install_launcher.py
```

설치 대상은 `practice/pyproject.toml`, `practice/uv.lock`, `practice/src/jazz_practice/`,
`practice/jazz`, `practice/runtime-ref`입니다. 실행기는 고정한 커밋의 캐시를 Git 원본과
대조하고 해당 의존성 환경으로 실행합니다. `uv run jazz status` 등 기존 CLI 명령도 됩니다.
`uv run jazz runtime`은 현재 버전·커밋·캐시 위치를 보여줍니다. 실행기 버전은 런타임·
커리큘럼 버전과 별도로 관리하며 설치 시 실제 기록과 로컬 `runtime.json`을 변경하지 않습니다.
프로젝트 스크립트 구성은
[uv 공식 문서](https://docs.astral.sh/uv/concepts/projects/config/#command-line-interfaces)를 따릅니다.

## MIDI 저장과 내보내기

`practice/sessions.sqlite3`는 원본 입력과 재생 이벤트의 저장소입니다. CSV에는 최종
자기보고만 남고 `task_id`로 세션을 연결합니다. 녹음 종료 자체는 연습 결과 보고가 아닙니다.
Git은 개인 기록을 보관하지 않습니다. 백업 시 서버를 종료한 뒤 CSV, SQLite, profile,
workflow-feedback, runtime.json을 개인 백업 위치에 함께 보관합니다. 캐시는 재생성할 수
있지만 고정한 커밋은 Git 이력에 보존해야 합니다. 전체 저장소 이력을 백업할 때는
`git bundle create <개인-백업-경로> --all`을 사용할 수 있습니다.
저장소 안의 `practice/backups/`도 Git에서 제외되지만 별도 장치의 백업을 대신하지 않습니다.

다운로드하는 `.jpm`은 표준 `.mid` 파일이 아닙니다. 최소 원본 보관 형식입니다.
첫 4바이트 `JPM1` 뒤에 다음 프레임을 반복합니다(모두 little-endian).

| 필드 | 형식 | 의미 |
| --- | --- | --- |
| at_ms | float64 | 세션 시작 기준 수신 시각(밀리초) |
| port | uint16 | 같은 세션의 입력 장치 번호 |
| length | uint16 | 다음 MIDI 메시지의 byte 수 |
| data | length bytes | 원본 메시지 bytes |

함께 받는 `.json`에는 과제의 발급 조건, 입력 장치 정보, 재생·일시정지·템포 적용
시각·패드 사용, 파생 측정값이 있습니다. 원본은 정정 보고나 시간 조정으로 바뀌지
않습니다. 이 형식은 향후 분석을 위해 입력을 보존할 뿐, 분석 규칙이나 점수 체계는 아닙니다.

## 웹 검증

```sh
uv run python -m unittest discover -s tests -v
uv run python review.py validate-curriculum
node --test tests/capture.test.mjs
```

선택적인 브라우저 통합 검증은 Playwright 개발 도구를 사용합니다. 스크립트가 임시
워크스페이스와 서버를 생성하고 종료·삭제하므로 실제 기록을 사용하지 않습니다.

```sh
npm install --prefix build/browser-tools playwright
PLAYWRIGHT_MODULE="$PWD/build/browser-tools/node_modules/playwright/index.mjs" \
CHROME_EXECUTABLE=/usr/bin/google-chrome node tests/browser.mjs
```

스크린샷은 `build/browser/`에 남습니다. MIDI 권한 거부, 가상 입력의 원본 보존·시간
계산, 템포/패드 재생, 결과·정정·스킵, 연결 끊김/재접속 복구와 모바일 화면을 확인합니다.
가상 MIDI 검증은 실제 키보드 연결이나 스피커 출력 품질을 검증한 것은 아닙니다.

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
