# Build src-tauri/resources/ for a Windows release bundle.
#
# Produces:
#   src-tauri/resources/dist/                 (app/dist build output)
#   src-tauri/resources/core/                 (core/ minus __pycache__)
#   src-tauri/resources/publish_agent.zip     (git archive snapshot of publish_agent HEAD)
#   src-tauri/resources/python-embed/         (pinned CPython embeddable amd64, SHA256-verified)
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$ResourcesDir = Join-Path $RootDir "src-tauri\resources"
$PublishAgentRepo = if ($env:KAIROS_PUBLISH_AGENT_REPO) { $env:KAIROS_PUBLISH_AGENT_REPO } else { Join-Path $env:USERPROFILE "LocalProjects\publish_agent" }

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

Write-Host "==> Done. Resources staged at $ResourcesDir"
