# Build linux/amd64 images on Windows (ASCII-only for PS 5.1 encoding safety)
param(
    [string]$Version = "1.0.0",
    [string]$Platform = "linux/amd64",
    [switch]$SkipTagLocal
)

$ErrorActionPreference = "Stop"

function Require-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker not found. Install Docker Desktop and restart the terminal."
    }
    docker version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker version failed" }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AiwordRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$AicheckwordRoot = Join-Path (Split-Path $AiwordRoot -Parent) "aicheckword"

if (-not (Test-Path (Join-Path $AicheckwordRoot "Dockerfile"))) {
    throw "aicheckword not found: $AicheckwordRoot"
}

Require-Docker

$AiwordImage = "aiword:$Version"
$AicheckwordImage = "aicheckword:$Version"

Write-Host "==> platform: $Platform"
Write-Host "==> aiword: $AiwordImage"
Write-Host "==> aicheckword: $AicheckwordImage"

& docker build --platform $Platform -t $AiwordImage -f (Join-Path $AiwordRoot "Dockerfile") $AiwordRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& docker build --platform $Platform -t $AicheckwordImage -f (Join-Path $AicheckwordRoot "Dockerfile") $AicheckwordRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipTagLocal) {
    docker tag $AiwordImage "aiword:local"
    docker tag $AicheckwordImage "aicheckword:local"
}

$DistDir = Join-Path $ScriptDir "dist"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
$lines = @(
    "version=$Version",
    "platform=$Platform",
    "built_at=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "aiword_image=$AiwordImage",
    "aicheckword_image=$AicheckwordImage"
)
$lines | Set-Content -Path (Join-Path $DistDir "manifest-$Version.txt") -Encoding ASCII

Write-Host ""
Write-Host "Done. Next: .\export-images-docker.bat $Version"
