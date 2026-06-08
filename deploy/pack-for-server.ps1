# Pack deploy bundle zip (ASCII-only)
param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = Join-Path $ScriptDir "dist"
$AiwordTar = Join-Path $DistDir "aiword-$Version.tar"
$AicheckwordTar = Join-Path $DistDir "aicheckword-$Version.tar"

foreach ($f in @($AiwordTar, $AicheckwordTar)) {
    if (-not (Test-Path $f)) {
        throw "Missing $f. Run export-images-docker.bat $Version first."
    }
}

$BundleName = "aiword-stack-$Version"
$StageDir = Join-Path $DistDir $BundleName
if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Include = @(
    "docker-compose.prod.yml",
    ".env.example",
    "server-deploy.sh",
    "server-load-images.sh",
    "backup.sh",
    "upgrade.sh",
    "build-images.bat",
    "build-images-docker.bat",
    "export-images.bat",
    "export-images-docker.bat",
    "pack-for-server.bat",
    "pack-for-server-docker.bat",
    "build-all.bat",
    "README.md",
    "nginx"
)
foreach ($item in $Include) {
    $src = Join-Path $ScriptDir $item
    if (Test-Path $src) {
        Copy-Item -Recurse -Force $src (Join-Path $StageDir $item)
    }
}

$ImagesDir = Join-Path $StageDir "images"
New-Item -ItemType Directory -Force -Path $ImagesDir | Out-Null
Copy-Item $AiwordTar $ImagesDir
Copy-Item $AicheckwordTar $ImagesDir
if (Test-Path (Join-Path $DistDir "manifest-$Version.txt")) {
    Copy-Item (Join-Path $DistDir "manifest-$Version.txt") $StageDir
}

Set-Content -Path (Join-Path $StageDir "VERSION") -Value $Version -Encoding ASCII

$ZipPath = Join-Path $DistDir "$BundleName.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

$tar = Get-Command tar -ErrorAction SilentlyContinue
if ($tar) {
    Push-Location $StageDir
    try {
        & tar -caf $ZipPath .
        if ($LASTEXITCODE -ne 0) { throw "tar failed" }
    } finally {
        Pop-Location
    }
} else {
    Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force
}

Write-Host "Bundle: $ZipPath"
