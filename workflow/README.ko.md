# 워크플로 개발

[English](README.md) · [한국어](README.ko.md)

`workflow/`는 코칭 지침·프로그램·발행을 개발하는 영역이고 실제 연습은 `../practice/`에
있습니다. Git 저장소는 상위 루트 하나입니다. 역할별 AGENTS.md를 먼저 읽습니다.

## 0.3.0 추천과 UI

‘새 연습’은 로컬 Codex CLI가 프로필, 최근 실제 연습, 라벨, 메모, 스킵 사유를 분석해
새 과제를 만드는 요청입니다. E01–E06, 선행 조건, 대표 목표는 필수 진도가 아닙니다.
기존 커리큘럼은 참고 예시로만 제공합니다. 완료/쉬움은 정확도나 숙련도 증거가 아닙니다.

목록이 첫 화면입니다. 생성 상태를 표시하고 검증한 항목을 추가하되 자동 진입하지
않습니다. 항목을 직접 열어 연습하고 ‘연습 완료’로 녹음·측정을 저장한 뒤 목록으로
돌아옵니다. 완료 항목에서 네 가지 난이도 라벨과 선택 메모를 남기거나 수정합니다.
피드백이 없어도 완료이며, 다시 하기는 별도 시도를 만듭니다. 스킵 사유는 선택입니다.
별도 연습 기록 탭과 진도 화면은 없습니다. 메트로놈 BPM은 분석된 실제 연주 BPM이
아니며 MIDI 음악 분석은 아직 구현하지 않았습니다.

## Codex 연결

`codex --version`, `codex login status`로 설치와 인증을 확인합니다. 필요하면 터미널에서
`codex login`을 실행합니다. 기존 ChatGPT 인증을 재사용하므로 별도 API_KEY는 필수가
아닙니다. 실제 생성에는 네트워크와 Codex 사용 가능 한도가 필요합니다.
`JAZZ_CODEX_BIN`으로 실행 파일을 지정할 수 있습니다.

앱은 빈 임시 디렉터리에서 `codex exec --sandbox read-only --ephemeral --json
--output-schema ...`를 실행하고 사용자 설정·도구·플러그인·셸·위임 기능을 끕니다.
명시적 맥락만 전송하며 기존 대화는 공유되지 않습니다. Codex는 JSON만 반환하고
앱이 출처 ID·필수 조건·음역·박 합계·반주 일치 등을 검증해 저장합니다. 로그인, 한도,
연결, 4분 시간 초과, 잘못된 출력은 별도 오류이며 고정 과제로 대체하지 않습니다.

맥락에는 최근 40개 과제와 최신 피드백, 완료/스킵 기록, 측정 요약, 생략 수를 담습니다.
원본 MIDI는 전송하지 않습니다. 맥락 500 KB 초과는 거부합니다. 결과와 원래 맥락은
Git에서 제외된 `practice/.recommendations/`에 보존합니다. 생성 중 기록·프로필·세션·
활성 버전이 바뀌면 저장하지 않습니다. 의미적으로 적절한 음악인지까지 완벽히 검증하는
검사기는 아닙니다. 악보는 4/4, 1–16마디, 손별 한 성부와 화음, 온/2분/4분/8분음표와
쉼표를 지원합니다. 타이·잇단음표·점음표는 지원하지 않습니다.

대화형 코칭도 활성 COACH.md, 같은 기록·스키마·저장 경로를 사용합니다. 저장소 루트에서:

```sh
uv run --project practice jazz recommend
uv run --project practice jazz recommend-context --output /tmp/jazz-context.json
uv run --project practice jazz recommendation-schema
uv run --project practice jazz accept-recommendation --context /tmp/jazz-context.json --input /tmp/jazz-recommendation.json
```

`recommend`와 별칭 `suggest`는 생성 후 목록에 저장합니다. `status`는 읽기만 합니다.
대화형 코치가 직접 분석할 때는 context와 schema를 읽어 JSON을 작성하고 accept로
검증·저장합니다. 원장이나 설치 소스를 직접 고치지 않습니다. `reflection TASK --input`
명령은 웹과 같은 라벨·선택 메모를 받습니다. 기존 상세 보고·정정 명령은 호환용입니다.

## 검증과 발행

개인 기록은 테스트에 사용하지 않습니다. 소스 편집 후 버전을 올리고 아래를 실행합니다.

```sh
uv lock
uv run python -m unittest discover -s tests -v
uv run python review.py validate-curriculum
node --test tests/capture.test.mjs tests/i18n.test.mjs tests/score.test.mjs
# 합성 프로필·기록만 사용하는 수동 실제 연결 검사 (계정 사용량 발생)
uv run python tests/codex_smoke.py --run
```

Playwright 브라우저 검사는 [영문 문서](README.md#web-validation)를 참고합니다.
새 버전 소스를 커밋·태그한 후 발행합니다.

```sh
uv run python publish.py --ref v0.3.0
```

발행은 새 버전 활성화를 우선합니다. 호환 미완료 과제는 원래 조건을 유지하고 비호환은
사유와 함께 retired로 종료합니다. 원문·MIDI를 보존하며 실패나 스킵으로 처리하지
않습니다. generated 과제는 커리큘럼 목록과 무관하게 자체 형식 지원 여부로 판단합니다.
`--cache-only`는 활성화하지 않고 캐시만 준비합니다. 활성화 후 서버를 다시 시작합니다.

`practice/runtime.json`은 로컬 활성 핀이고 `.runtime/`은 재생성 가능한 Git 스냅샷
캐시입니다. 개인 CSV, 프로필, MIDI, 추천 맥락/결과, 메모와 백업은 커밋하지 않습니다.
서버를 중지하고 이 개인 자료와 runtime.json을 별도로 백업합니다. Git은 개인 자료의
백업이 아닙니다. MIDI 포맷·복구·실행기 설명은 [영문 문서](README.md)를 참고합니다.

공식 문서: [비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode),
[인증](https://learn.chatgpt.com/docs/auth), [app-server](https://learn.chatgpt.com/docs/app-server).
