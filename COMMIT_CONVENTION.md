# 커밋 규칙 (Commit convention)

이 저장소에서는 **한 줄 제목**을 [Conventional Commits](https://www.conventionalcommits.org/) 스타일로 맞춥니다. PR·changelog·히스토리 검색이 쉬워집니다.

## 형식

```
<type>(<optional scope>): <short description>
```

- **제목은 72자 이내**, 마침표 없음, **명령형** (예: “add” not “added”).
- **본문(body)** 이 필요하면 제목 다음 빈 줄 뒤에 자유 형식(한국어 가능).
- **푸터**: `BREAKING CHANGE: …` 또는 `Fixes #123` 등.

## type

| type | 용도 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서만 변경 |
| `style` | 포맷·세미콜론 등 (동작 변화 없음) |
| `refactor` | 리팩터 (기능 변경 아님) |
| `perf` | 성능 개선 |
| `test` | 테스트 추가·수정 |
| `build` | 빌드·패키징 (Dockerfile, colcon 등) |
| `ci` | CI 설정 |
| `chore` | 기타 잡무 (버전만 등) |

## scope (선택)

모듈·영역을 짧게 적습니다. 예: `docker`, `stonefish_ros2`, `eroas_navigation`, `mvp_helm`.

## 예시

```text
docs(docker): consolidate README and add build instructions
build(docker): add integrated Dockerfile with stonefish context
fix(stonefish_ros2): correct scenario path in launch defaults
chore: update submodule pointers
```

Docker 브랜치 작업 예:

```text
docs(docker): README and commit convention
build(docker): root .dockerignore for integrated image
```

## 브랜치: `docker`에서 커밋하고 GitHub에 올리기

원격은 `origin`, 저장소 예: `https://github.com/RainingCodes/projectAlpha.git`.

### 1. 브랜치 확인

```bash
cd ~/new/projectAlpha
git status
git branch    # * docker 가 보여야 함
```

`main`에 있으면:

```bash
git switch docker
```

### 2. 스테이징·커밋

```bash
git add -A                    # 또는 git add docker/ .dockerignore COMMIT_CONVENTION.md
git status
git commit -m "docs(docker): add commit convention and docker layout"
```

규칙에 맞는 제목으로 바꿔 쓰면 됩니다.

### 3. 첫 푸시 (원격에 `docker` 브랜치가 아직 없을 때)

```bash
git push -u origin docker
```

`-u`는 이후 `git push`만으로 같은 브랜치를 밀 수 있게 **upstream**을 기억합니다.

### 4. 이후 푸시

```bash
git push
```

### 5. `main`에 합치기 (선택)

GitHub에서 **Pull Request**: `docker` → `main`, 리뷰 후 merge.  
로컬만 쓸 때:

```bash
git switch main
git pull origin main
git merge docker
git push origin main
```

(팀 규칙이 PR만 허용이면 PR만 사용.)

## 참고

- **서브모듈**을 바꿨다면 상위 저장소에서 서브모듈 커밋 해시가 바뀌므로, 그 변경도 함께 커밋합니다.
- **비밀·토큰**은 커밋하지 않습니다. `.env`, 키 파일은 `.gitignore`에 두세요.
