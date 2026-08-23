# Build src-tauri/resources/ for a Windows release bundle.
#
# Produces:
#   src-tauri/resources/dist/                 (app/dist build output)
#   src-tauri/resources/core/                 (core/ minus __pycache__)
#   src-tauri/resources/publish_agent.zip     (git archive snapshot of publish_agent HEAD)
#   src-tauri/resources/python-embed/         (pinned CPython embeddable amd64, SHA256-verified)
#   src-tauri/resources/ppt-master/           (pinned external workflow)
#   src-tauri/resources/codex-fleet/          (parallel image runner)
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$ResourcesDir = Join-Path $RootDir "src-tauri\resources"
$PublishAgentRepo = if ($env:KAIROS_PUBLISH_AGENT_REPO) { $env:KAIROS_PUBLISH_AGENT_REPO } else { Join-Path $env:USERPROFILE "LocalProjects\publish_agent" }
$PptMasterRepo = if ($env:KAIROS_PPT_MASTER_REPO) { $env:KAIROS_PPT_MASTER_REPO } else { Join-Path (Split-Path -Parent $RootDir) "ppt-master" }
$CodexFleetRepo = if ($env:KAIROS_CODEX_FLEET_REPO) { $env:KAIROS_CODEX_FLEET_REPO } else { Join-Path (Split-Path -Parent $RootDir) "codex-fleet" }
$PromptKitRepo = if ($env:KAIROS_PROMPT_KIT_REPO) { $env:KAIROS_PROMPT_KIT_REPO } else { Join-Path $RootDir "vendor\gongnyang-prompt-kit" }
$EngineLock = Get-Content -Raw (Join-Path $RootDir "presentation-engines.lock.json") | ConvertFrom-Json

Write-Host "==> Building app frontend (npm run build)"
Push-Location (Join-Path $RootDir "app")
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}

Write-Host "==> Staging resources\dist"
$DistDest = Join-Path $ResourcesDir "dist"
if (Test-Path $DistDest) { Remove-Item -Recurse -Force $DistDest }
New-Item -ItemType Directory -Force -Path $ResourcesDir | Out-Null
Copy-Item -Recurse -Force (Join-Path $RootDir "app\dist") $DistDest

Write-Host "==> Staging resources\core"
$CoreDest = Join-Path $ResourcesDir "core"
if (Test-Path $CoreDest) { Remove-Item -Recurse -Force $CoreDest }
New-Item -ItemType Directory -Force -Path $CoreDest | Out-Null
Get-ChildItem -Path (Join-Path $RootDir "core") -Recurse -Exclude "__pycache__" |
    Where-Object { $_.FullName -notmatch '\\__pycache__(\\|$)' -and $_.Extension -ne ".pyc" } |
    ForEach-Object {
        $relative = $_.FullName.Substring((Join-Path $RootDir "core").Length).TrimStart('\')
        $target = Join-Path $CoreDest $relative
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $target | Out-Null
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -Force $_.FullName $target
        }
    }

Write-Host "==> Snapshotting publish_agent -> resources\publish_agent.zip"
if (-not (Test-Path (Join-Path $PublishAgentRepo ".git"))) {
    throw "publish_agent repo not found at $PublishAgentRepo (set KAIROS_PUBLISH_AGENT_REPO to override)"
}
$ZipDest = Join-Path $ResourcesDir "publish_agent.zip"
if (Test-Path $ZipDest) { Remove-Item -Force $ZipDest }
git -C $PublishAgentRepo archive --format=zip -o $ZipDest HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed for publish_agent" }

Write-Host "==> Downloading embeddable Python (pinned 3.12.7 amd64)"
$PyVersion = "3.12.7"
$PyUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
# SHA256 computed from the official python.org download for
# python-3.12.7-embed-amd64.zip (verified 2026-07 by the build author)
$PySha256 = "0D57BB6CB078B74D23DBFE91F77D6780D45BED328911609F1F7EE2BA1606BF44"
$PyEmbedDest = Join-Path $ResourcesDir "python-embed"
if (Test-Path $PyEmbedDest) { Remove-Item -Recurse -Force $PyEmbedDest }
New-Item -ItemType Directory -Force -Path $PyEmbedDest | Out-Null
$PyZipPath = Join-Path $env:TEMP "python-$PyVersion-embed-amd64.zip"
Invoke-WebRequest -Uri $PyUrl -OutFile $PyZipPath
$ActualSha256 = (Get-FileHash -Path $PyZipPath -Algorithm SHA256).Hash
if ($ActualSha256.ToUpper() -ne $PySha256.ToUpper()) {
    throw "SHA256 mismatch for embeddable Python download: expected $PySha256, got $ActualSha256"
}
Expand-Archive -Path $PyZipPath -DestinationPath $PyEmbedDest -Force
Remove-Item -Force $PyZipPath
# The embeddable distro's ._pth pins sys.path to the python-embed dir only
# (cwd and PYTHONPATH are ignored), so `python -m core` can't see the sibling
# core/ package. Add the parent resources dir to sys.path.
Add-Content -Path (Join-Path $PyEmbedDest "python312._pth") -Value ".." -Encoding ascii
Add-Content -Path (Join-Path $PyEmbedDest "python312._pth") -Value "Lib\site-packages" -Encoding ascii
Add-Content -Path (Join-Path $PyEmbedDest "python312._pth") -Value "..\ppt-master\skills\ppt-master\scripts" -Encoding ascii

Write-Host "==> Installing presentation Python packages"
$SitePackages = Join-Path $PyEmbedDest "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null
py -3 -m pip install --disable-pip-version-check --target $SitePackages -r (Join-Path $RootDir "requirements-presentation.txt")
if ($LASTEXITCODE -ne 0) { throw "presentation dependency install failed" }

Write-Host "==> Staging PPT Master and codex-fleet"
if (-not (Test-Path (Join-Path $PptMasterRepo "skills\ppt-master\SKILL.md"))) {
    throw "ppt-master not found at $PptMasterRepo (set KAIROS_PPT_MASTER_REPO to override)"
}
if (-not (Test-Path (Join-Path $CodexFleetRepo "runners\codex_imagegen_runner.py"))) {
    throw "codex-fleet not found at $CodexFleetRepo (set KAIROS_CODEX_FLEET_REPO to override)"
}
if (-not (Test-Path (Join-Path $PromptKitRepo "skills\image-prompt\SKILL.md"))) {
    throw "gongnyang-prompt-kit not found at $PromptKitRepo"
}
$PptHead = (git -C $PptMasterRepo rev-parse HEAD).Trim()
$FleetHead = (git -C $CodexFleetRepo rev-parse HEAD).Trim()
$PromptKitHead = (git -C $PromptKitRepo rev-parse HEAD).Trim()
if ($PptHead -ne $EngineLock.'ppt-master'.commit) {
    throw "ppt-master commit mismatch: expected $($EngineLock.'ppt-master'.commit), got $PptHead"
}
if ($FleetHead -ne $EngineLock.'codex-fleet'.commit) {
    throw "codex-fleet commit mismatch: expected $($EngineLock.'codex-fleet'.commit), got $FleetHead"
}
if ($PromptKitHead -ne $EngineLock.'gongnyang-prompt-kit'.commit) {
    throw "gongnyang-prompt-kit commit mismatch: expected $($EngineLock.'gongnyang-prompt-kit'.commit), got $PromptKitHead"
}
$PptDest = Join-Path $ResourcesDir "ppt-master"
$FleetDest = Join-Path $ResourcesDir "codex-fleet"
$PromptKitDest = Join-Path $ResourcesDir "gongnyang-prompt-kit"
if (Test-Path $PptDest) { Remove-Item -Recurse -Force $PptDest }
if (Test-Path $FleetDest) { Remove-Item -Recurse -Force $FleetDest }
if (Test-Path $PromptKitDest) { Remove-Item -Recurse -Force $PromptKitDest }
New-Item -ItemType Directory -Force -Path $PptDest | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $FleetDest "runners") | Out-Null
New-Item -ItemType Directory -Force -Path $PromptKitDest | Out-Null
Copy-Item -Recurse -Force (Join-Path $PptMasterRepo "skills") $PptDest
Copy-Item -Force (Join-Path $PptMasterRepo "LICENSE") $PptDest
& (Join-Path $PyEmbedDest "python.exe") (Join-Path $RootDir "scripts\patch-ppt-master-compat.py") $PptDest
if ($LASTEXITCODE -ne 0) { throw "PPT Master compatibility patch failed" }
Copy-Item -Force (Join-Path $CodexFleetRepo "runners\codex_imagegen_runner.py") (Join-Path $FleetDest "runners")
Copy-Item -Force (Join-Path $CodexFleetRepo "LICENSE") $FleetDest
Copy-Item -Recurse -Force (Join-Path $PromptKitRepo "skills") $PromptKitDest
Copy-Item -Force (Join-Path $PromptKitRepo "LICENSE") $PromptKitDest
Copy-Item -Force (Join-Path $RootDir "presentation-engines.lock.json") $ResourcesDir

# bible_documents.db 는 tauri.release.conf.json 이 "../bible_documents.db" 로
# 번들에 굽는 공통 읽기 전용 자산이다. 설치된 번들은 쓸 수 없으므로 관주
# 인덱스는 반드시 여기, 빌드 타임에 만들어 두어야 한다.
Write-Host "==> Building verse cross-reference index into bible_documents.db"
$BibleDb = Join-Path $RootDir "bible_documents.db"
if (Test-Path $BibleDb) {
    py -3 (Join-Path $RootDir "scripts\build_verse_links.py")
    if ($LASTEXITCODE -ne 0) { throw "verse index build failed" }
} else {
    Write-Warning "bible_documents.db not found at $RootDir - skipping verse index"
    Write-Warning "(the tauri release build will fail on the missing bundle resource)"
}

Write-Host "==> Done. Resources staged at $ResourcesDir"
