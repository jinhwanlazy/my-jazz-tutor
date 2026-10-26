# 설계 결정

## 확정된 사용자 요구

- 피아노 기초 있음 / 재즈 처음 / 하루 30분. 대화는 사용자가 쓰는 언어로 응답한다.
- 기본 README는 영어이며, 한국어 원본은 `README.ko.md`로 보존한다. 웹 UI는 영어를
  기본으로 설정에서 영어·한국어를 전환하며, 선택은 브라우저에 저장한다. 전환 시
  진행 중인 MIDI 수집과 미저장 결과 입력을 유지하고 개인 기록·원문은 번역하지 않는다.
- Charlie Tran의 melody, rhythm, bass, voicing 어휘와 적용 방식을 참고한다.
- 대화로 과제 제시 → 실제 연습 → 자연어 노트 → 다음 과제의 루프.
- 하루에 여러 과제를 순서대로 진행한다. 어렵다면 보류/단순화하고, 쉬우면 기준을
  짧게 확인한 뒤 바로 다음 항목으로 이동한다. 30분은 하루 전체의 기본 시간 예산이다.
- 일일 연습 세션과 워크플로 편집 세션의 작업 디렉터리와 역할을 분리한다.
- CLI와 같은 기록·기준을 사용하는 로컬 웹 연습실을 제공한다. 과제 제시, 결과 입력,
  규칙 기반 피드백, 기록 조회와 정정, 메트로놈, 선택적 코드 패드를 한곳에서 사용한다.
- Web MIDI가 연결되면 세션 동안의 원본 입력을 저장한다. 음악적 자동 분석은 후속 과제다.

## 초기 범위

`my-jazz-tutor/` 하나의 Git monorepo에 `workflow/`와 `practice/`를 둔다.
실제 CSV는 `practice/practice.csv` 하나에만 있다. 실행 버전의 이력은 Git 커밋·태그로
보관한다. `practice/runtime.json`에 고정한 커밋을 `.runtime/<commit>/`에 캐시하고
두 경로 모두 Git에서 제외한다. 편집 중인 소스가 현재 연습 세션에 즉시 섞이지 않는다.
`practice/runtime-ref`는 새 작업 공간의 최초 기본값이며 기존 사용자의 고정 커밋을
자동 갱신하지 않는다. 캐시 삭제 후에도 로컬 핀의 동일 커밋에서 재구성한다.
예전 `practice/releases/` 복사본은 현재 트리에서 제거하고 기존 Git 이력에 보존한다.
개인 CSV·프로필·MIDI·개선 메모·보고서·백업은 로컬에 보관하며 Git에서 제외한다.
공유하는 프로필 예제에는 기본 설정만 두고 실제 사용자 관측은 넣지 않는다.
새 과제는 활성 버전으로 발급하며, 미완료 과제가 있으면 새 버전 활성화를 보류한다.
각 과제에 기준을 스냅샷으로 남겨 과거 판정을 새 커리큘럼으로 재해석하지 않는다.

CSV는 append-only event log다. `assigned`, `reported`, `cancelled`, `corrected`
사건을 task_id로 연결한다. 수정도 원문을 덮지 않고 새 사건으로 남긴다. 한 사용자
보고에 여러 조건이 섞이면 한 조건의 결과로 뭉개지 말고 대표 결과를 명시하거나
분리된 시도로 기록한다. 현재 버전은 한 과제에 하나의 최종 자기보고를 받는다.

동시에 미완료인 과제는 하나만 두지만 하루 과제 수에는 제한을 두지 않는다.
결과 기록 또는 취소 후 같은 날 다음 과제를 발급할 수 있다. 연습 전 스킵은 이유를
남긴 취소, 연습 후 중단은 실제 조건과 원문을 남긴 결과 기록으로 구분한다.
취소한 항목과 어렵다고 보고한 미통과 항목은 그날 같은 항목·키의 자동 추천에서
보류한다. 다른 과제도 선행 조건을 충족해야 하며, 후보가 없으면 마무리 또는 조건
단순화를 안내한다. 명시적으로 재시도할 수 있고 새 결과가 있으면 그 결과가 우선한다.
보류는 영구 제외가 아니며 다음 날 다시 후보가 된다. 취소일과 실제 연습일을 쓰고,
과거 결과를 오늘 정정했다는 이유로 오늘의 시도로 재해석하지 않는다.

쉬운 과제는 기준을 짧게 확인하고 당일 바로 다음 항목으로 간다. 성공 기준과 후일
재현 기준은 유지한다. 하루 시간은 과제별 보고를 합산하며 준비·듣기·기록도 예산에
포함한다. 시간이 알려지지 않은 기록은 0분으로 바꾸지 않고 남은 시간을 미확인으로
둔다. 알려진 시간만으로 예산에 도달하면 마무리를 권하지만 추가 연습을 차단하지 않는다.

통과는 고정 조건에서 자기보고한 음·박자·무중단·연속 성공 횟수에 기반한다.
근거가 없는 항목은 미평가다. 후일 재현은 같은 과제 조건의 성공을 2일 이상
간격으로 다시 보고했을 때만 표시한다. 이 기준은 앱 운영 정의이며 음악 능력의
객관적 인증이 아니다. 전이 추정은 하지 않고 실제로 시도한 키를 구분해 보여준다.

초기 커리큘럼은 자체 제작 연습 6개와 C 키의 대표 목표 6개다. F/Bb는 이후 전이
확인에 쓸 수 있으나 모든 조합을 필수 진도로 간주하지 않는다. 스탠더드 곡의 악보,
판본, 키가 아직 정해지지 않았으므로 Autumn Leaves의 마디·멜로디를 창작하지 않는다.
전체 수년 로드맵과 '재즈 마스터' 점수는 아직 설계하지 않았다.

## 평가와 시각화

- 연습량: 실제 결과를 보고한 과제 수, 알려진 실제 연습 시간.
- 범위: 시도한 항목과 키. 미평가와 실패를 구분.
- 성공: 발급 조건 통과 / 후일 동일 조건 재현. 자기보고 기반 표시.
- 고정 진도: 현재 버전의 대표 목표 목록. 변경 시 버전과 분모 변경을 표시.
- 조건별 히트맵과 근거 기록을 제공한다. 방사형 면적을 실력/체적 점수로 쓰지 않는다.

## 다음에 검토할 것

실제 2주 사용 후 기록 부담, 추천의 유용성, 후일 재현 여부를 검토한다.
사용자 피드백 없이 청음/스윙 자동 채점, 모든 키, 방대한 과제 생성기로 확장하지 않는다.
MIDI의 음·박자·스윙 분석과 자동 피드백 대체는 아직 설계하거나 구현하지 않는다.

## 웹 연습실 — 0.2.0

Python 표준 라이브러리 서버를 127.0.0.1에만 열고, 브라우저는 같은 서버의 API로
기존 발급·보고·정정·취소 함수를 사용한다. 외부 LLM 호출이나 호스팅은 없다.
페이지를 여는 것만으로 과제가 발급되거나 연습 실적이 만들어지지 않는다.
웹의 피드백은 보고한 조건·검사 결과와 기존 기준의 비교이며 자유 대화형 코칭은 아니다.

Web Audio의 오디오 시계 하나로 메트로놈과 마디별 코드 패드를 예약한다. 패드는
기본 꺼짐이며 과제의 코드 진행을 반복한다. 템포와 두 음량은 연습 중 변경할 수 있다.
템포 변경은 아직 예약하지 않은 다음 박부터 적용하고 적용 시각을 기록한다.
일시정지 후 재생은 첫 마디에서 다시 시작한다. 숨겨진 탭과 오디오 중단에서는
재생을 멈춘다. 사용자가 시작·종료한 세션 구간 동안 MIDI 수집은 일시정지 중에도 유지한다.

과제별 여러 재생 세션을 `practice/sessions.sqlite3`에 연결한다. 원본 MIDI bytes와
세션 시작 기준 밀리초·입력 장치 번호를 BLOB 청크로 저장한다. 재생·일시정지·실제
템포 적용·패드·장치 정보는 별도 이벤트다. CSV와 MIDI를 서로의 대체 근거로 쓰지 않는다.
패드 출력은 MIDI 입력에 합성하지 않는다. 기본 선택은 연결된 모든 입력이며 사용자가
특정 장치를 고를 수 있다. 장치 SysEx 권한은 요청하지 않는다.

3초마다 먼저 브라우저 IndexedDB에 저장한 뒤 서버에 전송한다. 세션 ID와 청크 순서로
중복 전송을 구분하고 저장한 청크를 덮어쓰지 않는다. 서버 확인 후에만 브라우저의
청크를 지운다. 재접속 시 잔여 청크를 전송하고 중단 상태를 남긴다. 마지막 체크포인트
이후 브라우저가 강제 종료되면 미저장 입력은 복구할 수 없으므로 완전한 기록으로 표시하지 않는다.

자동 입력 후보는 다음처럼 원본에서 파생한다. 사용자가 확인·수정해야 CSV에 보고된다.

- BPM: 마지막 Note On 시점의 메트로놈 설정. 입력이 없으면 마지막 재생 설정.
  연주를 분석해 측정한 BPM이 아니다. 설정 변경 이력도 별도로 보존한다.
- MIDI 구간: 첫 Note On부터 마지막 Note Off 또는 해당 서스테인 해제까지.
  앞뒤의 무입력만 제외하며 중간 쉼은 포함한다. MIDI clock·제어 메시지만으로 늘리지 않는다.
- Note Off 누락·장치 변경/끊김·수집 중단이면 MIDI 구간은 미확인이다.
- MIDI 구간을 측정할 수 없으면 일시정지를 뺀 재생 시간을 대안으로 표시한다.
  브라우저 복구로 종료한 세션은 실제 시간을 직접 입력한다. 준비·회고 시간은 필요하면 더한다.

원본은 자르지 않으며 결과 정정도 녹음을 변경하지 않는다. 입력 유무만으로 성공 검사나
연속 성공 횟수를 자동 채우지 않는다. 재생 정보는 기존 material과 분리해 저장하여
같은 조건의 과거 성공을 무효화하지 않는다. 새 런타임은 기존 발행·활성화 경계를 따른다.

## Score and live MIDI display — 0.2.6

The score is a display derived from each assignment's own material and conditions.
It does not use pad voicings, rewrite historical target snapshots, or change scoring.
The six current exercises in C, F, and Bb have grand-staff notation; unsupported
conditions show the existing written instructions instead of fabricated notation.
Whole-note exercises, Charleston attacks on 1 and 2&, and the improvisation/rest
structure remain distinct. The vamp specifies bass attacks but not their duration,
so diamonds mark those onsets. Improvisation does not gain a prescribed melody.
Charleston eighth notes illustrate short attacks; their exact displayed durations
do not add a requirement beyond the assigned attack positions and short playing.

A bounded beat timeline uses the scheduled audio clock, including tempo changes
and loop positions. MIDI timestamps are mapped to that timeline using
`AudioContext.getOutputTimestamp()` when available, with `currentTime` as fallback.
The cursor and blue key-press marks share this mapping; timing is not quantized or
scored. Physical device latency can still affect alignment. This is a visualization,
not a timing-accuracy measurement or a replacement for the original recording.

The live buffer shows the current pass, carries held notes across loop boundaries,
and resets when playback resumes from bar 1. Pauses and disconnects truncate open
tails with dashed lines. Tails end at key release, not pedal release. Input during
pauses stays in raw capture but has no displayed beat position. Hand placement uses
assigned pitches, then pitch range; it never claims to detect the player's hands.
The live buffer is bounded and is not a history/replay format. History continues to
retain the original binary MIDI and session events. Display-language switching keeps
the active capture, live notes, and draft report intact.

SVG rendering and a bundled, unmodified Bravura font need no external network or
notation library at runtime. Attribution and source pin are in `THIRD_PARTY.md`.
The notation assets are part of the immutable Git runtime and its hash manifest.

## Continuous score and unified practice controls — 0.2.7

Task instructions, assigned conditions, and success criteria precede the practice
area. Written pitches and the chord progression are expandable; unsupported
notation opens them automatically. Score, playback, and tempo controls share one
card with a single start/pause/resume button and finish button. Sound and MIDI
settings are expandable. Assigned target BPM remains separate from playback BPM.

Every bar is rendered on one horizontal staff, with one linear beat-to-position
mapping for targets, the cursor, and live input. Bar margins no longer create gaps
in that mapping, and held-note tails remain continuous across bar boundaries.
Four-bar page replacement is removed. Following computes a clamped scroll offset
on each audio-driven animation frame: a fitting score stays fixed, while a wider
score follows continuously until its end. Only a loop returns to the beginning.
Following can be disabled for manual scrolling. Live buffers retain the existing
loop, pause, disconnect, and language-switch semantics.

The staff omits bar numbers and hand labels. Whole-note interiors are transparent
so staff and ledger lines remain visible. These presentation changes do not change
assigned material, success criteria, raw MIDI capture, or historical evidence.

## 출처와 구분

- 원영상과 제작자의 설명: https://www.youtube.com/watch?v=RiCQYWPEhjc
- 제작자: https://www.novujazzacademy.com/
- 참고한 상세 요약: https://videohighlight.com/v/RiCQYWPEhjc?aiFormatted=false&language=en&mediaType=youtube&summaryId=5Pp1mFQnQA6R0IL2GJ5X&summaryType=default
- Codex 지침 발견: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- 현재 수행/학습 판단 차이의 참고 실험(재즈 교육 실험은 아님): https://pubmed.ncbi.nlm.nih.gov/11486923/

전체 원영상 자막을 확보하지 못했다. 이 커리큘럼, 수치 기준, 분리 구조는 대화에서
만든 설계이며 Charlie Tran의 공식 강의나 원영상의 완전한 전사가 아니다.
