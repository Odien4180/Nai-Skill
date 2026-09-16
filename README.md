# NovelAI Image Agent Skill

NovelAI의 공식 Image Generation API를 Codex, Claude, GitHub Copilot에서 사용할 수 있게 해 주는 이식 가능한 Agent Skill입니다.

지원 범위:

- Text-to-image, Image-to-image, Inpaint/Outpaint, Enhance
- V4/V5 구조화 프롬프트와 다중 캐릭터 좌표
- Vibe Transfer 인코딩과 다중 Vibe
- Precise Reference (character/style/fidelity)
- Director Tools: 배경 제거, line art, sketch, colorize, emotion, declutter
- Upscale, tag suggestions, 스트리밍 생성
- 공식 API에 새 필드/엔드포인트가 추가될 때를 위한 raw JSON/endpoint 호출

API 호출 도구는 Python 표준 라이브러리만 사용합니다. Windows에서는 토큰을 파일이나 환경 변수 대신 Windows 자격 증명 관리자에 저장합니다.

## 설치

Windows에서 저장소 폴더를 연 뒤:

```powershell
.\install.ps1
```

또는 탐색기/명령 프롬프트에서:

```bat
install.cmd
```

설치기를 실행하면 Codex, Claude, Copilot 선택 화면이 나타납니다.

- 위/아래 방향키: 항목 이동
- Space: 설치 항목 체크 또는 해제
- Enter: 선택 확정 후 설치

처음에는 세 플랫폼이 모두 체크되어 있습니다. 설치가 끝나면 NovelAI Persistent API Token을 숨김 입력으로 받고 Windows 자격 증명 관리자에 저장합니다.

방향키 선택 화면에서 체크한 플랫폼에 기존 설치가 있으면 해당 `novelai-image` 폴더를 업데이트한 뒤 토큰 입력 단계로 계속 진행합니다. 설치 중 오류가 발생하면 `install.cmd` 창이 즉시 닫히지 않고 오류를 확인할 수 있게 대기합니다.

방향키 UI 없이 대상을 직접 지정하는 자동 설치 방식도 지원합니다:

```powershell
.\install.ps1 -Targets Codex,Claude
.\install.ps1 -Targets Copilot
```

프로젝트에만 설치:

```powershell
.\install.ps1 -Scope Project -ProjectRoot 'C:\path\to\project'
```

대상 위치:

| 환경 | 사용자 설치 | 프로젝트 설치 |
|---|---|---|
| Codex | `~/.codex/skills/novelai-image` | `.agents/skills/novelai-image` |
| Claude | `~/.claude/skills/novelai-image` | `.claude/skills/novelai-image` |
| Copilot | `~/.copilot/skills/novelai-image` | `.github/skills/novelai-image` |

`-Targets`로 대상을 직접 지정한 비대화형 설치에서는 기존 설치 보호를 위해 중단합니다. 해당 스킬 폴더를 업데이트하려면 `-Force`를 명시하세요. 실제 복사 없이 확인하려면 `-WhatIf`를 사용합니다.

토큰 입력을 건너뛰어야 하는 자동 설치 환경에서는:

```powershell
.\install.ps1 -SkipTokenPrompt
```

## 인증

설치기가 NovelAI Persistent API Token을 숨김 입력으로 받고 Windows 자격 증명 관리자의 `NovelAISkill:NOVELAI_API_TOKEN` 항목에 저장합니다. 이미 저장된 토큰이 있으면 Enter만 눌러 기존 값을 유지할 수 있습니다. 성공적으로 저장되면 과거 설치기가 만든 사용자 범위 `NOVELAI_API_TOKEN` 환경 변수는 제거됩니다.

API 클라이언트는 실행할 때마다 자격 증명 관리자에서 토큰을 읽으며 화면이나 로그에 출력하지 않습니다. 비 Windows 환경과 자동화 환경에서는 `NOVELAI_API_TOKEN`을 대체 수단으로 사용할 수 있습니다. 현재 PowerShell 세션에서만 임시로 설정하는 예:

```powershell
$env:NOVELAI_API_TOKEN = Read-Host 'NovelAI Persistent API Token'
```

설치 후 에이전트를 재시작하거나 스킬 목록을 새로고침한 다음 `novelai-image` 스킬을 지정하거나 NovelAI 이미지 생성을 요청하세요. 토큰을 변경한 경우에는 에이전트를 재시작할 필요가 없습니다.

## 직접 확인

라이브 생성 없이 클라이언트와 페이로드를 확인할 수 있습니다.

```powershell
python .\skills\novelai-image\scripts\novelai_image.py --help
python .\skills\novelai-image\scripts\novelai_image.py generate --request request.json --output-dir output --dry-run
```

NovelAI는 생성 요청이 사람의 동작으로 시작되어야 하며 과도한 자동화를 허용하지 않습니다. 이미지 생성은 구독/Anlas를 사용할 수 있습니다.

## 공식 문서

- [NovelAI Image Generation](https://docs.novelai.net/en/image/)
- [NovelAI Image API Swagger](https://image.novelai.net/docs/index.html)
- [NovelAI Terms of Service](https://novelai.net/terms)
