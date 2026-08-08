1. **드롭존 클릭 시 파일 탐색기 열기 기능 추가 (`saas_web.py`)**
   - 사용자 편의성 향상을 위해 전체 드롭존 영역(`dropZone`, `batchDropZone`)을 클릭하면 해당하는 파일 입력(input type="file") 필드를 프로그래밍 방식으로 클릭하여 파일 탐색기가 열리도록 개선합니다.
   - 폼 내부의 입력 요소(INPUT), 버튼(BUTTON), 라벨(LABEL)을 클릭할 때는 이벤트가 전파되어 파일 탐색기가 열리지 않도록 `['INPUT', 'BUTTON', 'LABEL'].includes(e.target.tagName)` 조건을 추가하여 방어합니다.
   - `saas_web.py` 내의 HTML `script` 영역에 `replace_with_git_merge_diff`를 사용하여 코드를 적용합니다.

2. **UI 테스트 업데이트 (`tests/test_saas_web.py`)**
   - 새롭게 추가된 기능에 대해 `test_get_ui_includes_binary_file_size_validation` 테스트 내에 `assertIn` 단언문을 추가합니다.
   - `assertIn("dropZone.addEventListener('click'", html)`
   - `replace_with_git_merge_diff`를 사용하여 `tests/test_saas_web.py` 코드를 업데이트합니다.

3. **CHANGELOG 및 Palette 저널 기록**
   - `CHANGELOG.md`의 끝에 변경 사항을 `cat << 'EOF' >> CHANGELOG.md` 명령어로 추가합니다.
   - `.jules/palette.md` 최상단에 새로운 배움(학습)과 조치를 추가합니다. (드롭존 전체 영역을 파일 업로드 타겟으로 만들어 사용자 경험 향상). `bash`의 임시 파일을 사용하여 맨 앞에 추가합니다.

4. **100% 테스트 커버리지 확인**
   - `python3 -m pip install coverage && python3 -m coverage run -m unittest discover -s tests && python3 -m coverage report -m` 명령을 실행하여 모든 테스트가 성공하고 커버리지가 100%인지 확인합니다.

5. **사전 커밋 단계 완료**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

6. **제출(Submit)**
   - "🎨 Palette: 드롭존 클릭하여 파일 선택 기능 추가" 형식의 PR 제목과 적절한 설명을 포함하여 커밋 및 제출합니다. PR 설명에는 무엇을, 왜, 이전/이후(변경사항), 접근성에 대한 설명이 포함되어야 합니다.
