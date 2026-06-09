# Export built images to tar.gz (preferred) or tar (ASCII-only)
param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker not found"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ScriptDir "dist"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

$AiwordImage = "aiword:$Version"
$AicheckwordImage = "aicheckword:$Version"

foreach ($img in @($AiwordImage, $AicheckwordImage)) {
    docker image inspect $img 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Image missing: $img. Run build-images-docker.bat $Version first."
    }
}

$hasGzip = $null -ne (Get-Command gzip -ErrorAction SilentlyContinue)

if ($hasGzip) {
    $AiwordOut = Join-Path $DistDir "aiword-$Version.tar.gz"
    $AicheckwordOut = Join-Path $DistDir "aicheckword-$Version.tar.gz"

    Write-Host "==> save gzip $AiwordImage"
    docker save $AiwordImage | gzip -1 > $AiwordOut
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "==> save gzip $AicheckwordImage"
    docker save $AicheckwordImage | gzip -1 > $AicheckwordOut
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Done: $AiwordOut , $AicheckwordOut"
} else {
    $AiwordTar = Join-Path $DistDir "aiword-$Version.tar"
    $AicheckwordTar = Join-Path $DistDir "aicheckword-$Version.tar"

    Write-Host "WARN: gzip not found, exporting uncompressed .tar"
    Write-Host "==> save $AiwordImage"
    docker save -o $AiwordTar $AiwordImage
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "==> save $AicheckwordImage"
    docker save -o $AicheckwordTar $AicheckwordImage
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "Done: $AiwordTar , $AicheckwordTar"
}
