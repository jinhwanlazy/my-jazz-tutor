# My Jazz Tutor

Your private AI jazz piano tutor, powered by Codex.

이 프로젝트는 배포되는 서비스가 아닙니다. **로컬에서 Codex 구독과 연동해 개인
피아노 튜터(private piano tutor)를 대신할 존재를 만들어보려는 시도**입니다.
Codex 대화 세션으로 과제와 연습 맥락을 다루고, 로컬 웹 연습실로 메트로놈·반주·
기록을 지원합니다. 현재 웹 피드백은 기록과 기준을 비교하는 규칙 기반입니다.

`my-jazz-tutor/` 하나의 Git monorepo에서 연습과 워크플로 개발을 관리합니다.
역할에 맞는 작업 디렉터리를 열어 사용하고, 각 디렉터리의 `AGENTS.md`를 따릅니다.
아래 경로와 명령은 저장소 루트를 기준으로 합니다.

| 작업 영역 | 경로 | 첫 메시지 예시 |
| --- | --- | --- |
| 일일 연습 | [`practice/`](practice/) | `오늘 연습 시작하자. 기록을 읽고 과제 하나 제시해줘.` |
| 워크플로 편집 | [`workflow/`](workflow/) | `연습 기록을 읽고 추천 규칙의 문제점을 검토해줘.` |

CLI에서도 각 디렉터리에서 별도 세션을 시작할 수 있습니다.

```sh
codex -C practice
codex -C workflow
```

두 명령은 서로 다른 세션에서 실행합니다. 디렉터리를 바꾸는 것만으로 기존
세션의 역할이 초기화되지는 않으므로 새 세션을 여는 것을 권장합니다.

Git 작업은 루트에서 두 영역을 함께 관리합니다. `workflow/`와 `practice/`는
하위 디렉터리이며, 중첩 저장소나 서브모듈을 사용하지 않습니다. 소스·테스트·문서,
프로필 예제와 최초 실행용 Git ref를 추적합니다. 실행 버전의 이력은 Git 커밋·태그로
관리합니다. **개인 연습 기록은 로컬에만
보관합니다.** 원본 CSV·개인 프로필·MIDI 저장소·개선 메모·생성 보고서와 백업은
루트 `.gitignore`로 제외합니다. 가상 환경·캐시·개발 미리보기도 제외합니다.

처음 clone한 뒤에는 [practice/README.md](practice/README.md)의 안내대로 프로필 예제를
복사해 자신의 선호를 적습니다. CSV와 MIDI 저장소는 실제 사용 시 생성됩니다.
Git으로 되돌리거나 새로 clone해도 개인 기록은 복원되지 않으므로 별도로 백업합니다.

연습 기록은 `practice/practice.csv` 한 곳에만 있습니다. 편집용 세션은 이를
읽어서 설계를 개선할 수 있지만, 테스트 결과를 실제 기록에 쓰지 않습니다.
연습용은 로컬 `practice/runtime.json`에 고정한 Git 커밋을 사용합니다.
실행 파일은 Git에서 제외한 `practice/.runtime/<commit>/`에 필요할 때 생성됩니다.
캐시를 지워도 같은 커밋에서 복원하며, 편집 중인 소스 변경은 자동으로 반영되지 않습니다.
새 작업 공간의 첫 실행은 `practice/runtime-ref`의 태그를 사용해 로컬 커밋을 고정합니다.

```sh
uv run --project practice jazz status
uv run --project practice jazz report
uv run --project practice jazz runtime
```

생성된 `practice/reports/index.html`을 브라우저로 열면 됩니다. 외부 서버,
추가 LLM API 키, Streamlit 서버가 필요하지 않습니다. Python 실행 의존성은
프로젝트별 `uv` 환경에서 관리합니다.

0.2.0부터 로컬 웹 연습실도 제공합니다. 웹을 지원하는 버전이 활성화된 뒤
저장소 루트에서 다음 명령 하나로 서버와 브라우저를 실행합니다.

```sh
uv run --project practice jazz
```

과제 제시·연습 기록·규칙 기반 피드백·기록 조회·정정을 한 화면에서 진행합니다.
내장 메트로놈과 선택적 코드 패드, Web MIDI 원본 저장 및 BPM·시간 자동 입력을
제공합니다. MIDI의 음악적 분석은 아직 하지 않습니다. 원본 MIDI는
`practice/sessions.sqlite3`에 보관합니다. 시작·버전 활성화·개발 미리보기·복구 안내는
[workflow/README.md](workflow/README.md#웹-연습실)에 있습니다.

인자가 없는 `jazz`는 `serve --open`을 실행합니다. 별도의 환경 활성화나 설치 명령이
필요하지 않습니다. 포트를 바꾸려면 `uv run --project practice jazz serve --open --port 8768`을
사용합니다. 실행기는 로컬에 고정한 커밋을 따르며, 미완료 과제를 취소하거나 새 버전을
자동 활성화하지 않습니다.

역할 분리는 디렉터리별 지침과 발행 버전에 의한 것입니다. OS 파일 권한으로
다른 디렉터리에 대한 접근을 차단하는 보안 샌드박스는 아닙니다.
