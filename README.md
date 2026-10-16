# Jazz Piano

`jazz-piano/` 하나의 Git monorepo에서 연습과 워크플로 개발을 관리합니다.
역할에 맞는 작업 디렉터리를 열어 사용하고, 각 디렉터리의 `AGENTS.md`를 따릅니다.

| 작업 영역 | 경로 | 첫 메시지 예시 |
| --- | --- | --- |
| 일일 연습 | `/home/hwan/jazz-piano/practice` | `오늘 연습 시작하자. 기록을 읽고 과제 하나 제시해줘.` |
| 워크플로 편집 | `/home/hwan/jazz-piano/workflow` | `연습 기록을 읽고 추천 규칙의 문제점을 검토해줘.` |

CLI에서도 각 디렉터리에서 별도 세션을 시작할 수 있습니다.

```sh
codex -C /home/hwan/jazz-piano/practice
codex -C /home/hwan/jazz-piano/workflow
```

두 명령은 서로 다른 세션에서 실행합니다. 디렉터리를 바꾸는 것만으로 기존
세션의 역할이 초기화되지는 않으므로 새 세션을 여는 것을 권장합니다.

Git 작업은 루트에서 두 영역을 함께 관리합니다. `workflow/`와 `practice/`는
하위 디렉터리이며, 중첩 저장소나 서브모듈을 사용하지 않습니다. 소스·테스트·문서,
연습 프로필·원본 CSV, 활성 버전과 버전별 발행본을 추적합니다. 가상 환경·캐시·
개발 미리보기·생성 보고서는 루트 `.gitignore`로 제외합니다. 원격 저장소는 없습니다.

연습 기록은 `practice/practice.csv` 한 곳에만 있습니다. 편집용 세션은 이를
읽어서 설계를 개선할 수 있지만, 테스트 결과를 실제 기록에 쓰지 않습니다.
연습용은 `practice/active-version`이 가리키는 발행본을 사용합니다.
편집 중인 소스 변경은 자동으로 연습용에 적용되지 않습니다.

```sh
/home/hwan/jazz-piano/practice/jazz status
/home/hwan/jazz-piano/practice/jazz report
```

생성된 `practice/reports/index.html`을 브라우저로 열면 됩니다. 외부 서버,
추가 LLM API 키, Streamlit 서버가 필요하지 않습니다. Python 실행 의존성은
프로젝트별 `uv` 환경에서 관리합니다.

역할 분리는 디렉터리별 지침과 발행 버전에 의한 것입니다. OS 파일 권한으로
다른 디렉터리에 대한 접근을 차단하는 보안 샌드박스는 아닙니다.
