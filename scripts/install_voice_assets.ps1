#requires -Version 5.1
[CmdletBinding()]
param(
    [int]$BuildThreads = 4,
    [switch]$SkipWhisperBuild,
    [switch]$SkipModelDownloads
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WhisperSource = Join-Path $ProjectRoot "apps\whisper.cpp"
$WhisperBuild = Join-Path $WhisperSource "build"
$ModelDirectory = Join-Path $ProjectRoot "models\whisper"
$KokoroDirectory = Join-Path $ProjectRoot "models\kokoro"

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install it and reopen PowerShell."
    }
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Description
    )
    Write-Host ""
    Write-Host "== $Description ==" -ForegroundColor Cyan
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Assert-DownloadedFile {
    param(
        [string]$Path,
        [long]$MinimumBytes,
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not downloaded: $Path"
    }
    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt $MinimumBytes) {
        throw "$Description is unexpectedly small ($($file.Length) bytes): $Path"
    }
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    Write-Host ("SHA256 {0}  {1}" -f $hash.Hash, $Path)
}

function Download-File {
    param(
        [string]$Uri,
        [string]$Destination,
        [long]$MinimumBytes
    )

    if (Test-Path -LiteralPath $Destination) {
        $existing = Get-Item -LiteralPath $Destination
        if ($existing.Length -ge $MinimumBytes) {
            Write-Host "Already present: $Destination"
            return
        }
        Remove-Item -LiteralPath $Destination -Force
    }

    $temporary = "$Destination.partial"
    Write-Host "Downloading: $Uri"
    Invoke-WebRequest -Uri $Uri -OutFile $temporary -UseBasicParsing

    $downloaded = Get-Item -LiteralPath $temporary
    if ($downloaded.Length -lt $MinimumBytes) {
        Remove-Item -LiteralPath $temporary -Force
        throw "Downloaded file is unexpectedly small: $Destination"
    }

    Move-Item -LiteralPath $temporary -Destination $Destination -Force
    $hash = Get-FileHash -LiteralPath $Destination -Algorithm SHA256
    Write-Host ("SHA256 {0}  {1}" -f $hash.Hash, $Destination)
}

Write-Host "V local voice asset setup" -ForegroundColor Green
Write-Host "Project: $ProjectRoot"
Write-Host "No microphone will be opened by this installer."

if (-not $SkipWhisperBuild) {
    Assert-Command "git"
    Assert-Command "cmake"

    $vswhereCandidates = @(
        "$env:ProgramFiles(x86)\Microsoft Visual Studio\Installer\vswhere.exe",
        "$env:ProgramFiles\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    $vswhere = $vswhereCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $vswhere) {
        throw "Visual Studio 2022 C++ Build Tools were not found. Install the Desktop development with C++ workload, then retry."
    }

    $installation = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $installation) {
        throw "Visual Studio C++ x64 build tools were not found. Install the Desktop development with C++ workload."
    }

    New-Item -ItemType Directory -Force (Split-Path $WhisperSource -Parent) | Out-Null

    if (-not (Test-Path -LiteralPath (Join-Path $WhisperSource ".git"))) {
        if (Test-Path -LiteralPath $WhisperSource) {
            throw "The target folder exists but is not a Git checkout: $WhisperSource"
        }
        Invoke-Native "git" @(
            "clone", "--depth", "1", "--branch", "v1.9.5",
            "https://github.com/ggml-org/whisper.cpp.git",
            $WhisperSource
        ) "Clone official whisper.cpp v1.9.5 source"
    } else {
        $tag = & git -C $WhisperSource describe --tags --exact-match 2>$null
        if ($tag -ne "v1.9.5") {
            throw "Existing whisper.cpp checkout is not exactly v1.9.5. Remove or rename '$WhisperSource' before installing this pinned build."
        }
    }

    Invoke-Native "cmake" @(
        "-S", $WhisperSource,
        "-B", $WhisperBuild,
        "-DWHISPER_BUILD_SERVER=ON",
        "-DWHISPER_BUILD_EXAMPLES=ON",
        "-DWHISPER_BUILD_TESTS=OFF",
        "-DGGML_CUDA=OFF"
    ) "Configure CPU-only whisper.cpp server"

    Invoke-Native "cmake" @(
        "--build", $WhisperBuild,
        "--config", "Release",
        "--target", "whisper-server",
        "--parallel", "$BuildThreads"
    ) "Build whisper-server"

    $serverCandidates = @(
        (Join-Path $WhisperBuild "bin\Release\whisper-server.exe"),
        (Join-Path $WhisperBuild "bin\whisper-server.exe")
    )
    $serverPath = $serverCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $serverPath) {
        throw "Build completed but whisper-server.exe was not found under $WhisperBuild."
    }
    Write-Host "Whisper server: $serverPath" -ForegroundColor Green
}

if (-not $SkipModelDownloads) {
    New-Item -ItemType Directory -Force $ModelDirectory | Out-Null
    New-Item -ItemType Directory -Force $KokoroDirectory | Out-Null

    $whisperDownload = Join-Path $WhisperSource "models\download-ggml-model.cmd"
    $vadDownload = Join-Path $WhisperSource "models\download-vad-model.cmd"
    if (-not (Test-Path -LiteralPath $whisperDownload) -or -not (Test-Path -LiteralPath $vadDownload)) {
        throw "The pinned whisper.cpp model download scripts are missing. Run without -SkipWhisperBuild to clone the source."
    }

    Write-Host ""
    Write-Host "== Download multilingual Whisper base model ==" -ForegroundColor Cyan
    & $whisperDownload "base" $ModelDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Whisper base model download failed with exit code $LASTEXITCODE."
    }
    Assert-DownloadedFile (Join-Path $ModelDirectory "ggml-base.bin") 100000000 "Whisper base model"

    Write-Host ""
    Write-Host "== Download Silero VAD v6.2.0 model ==" -ForegroundColor Cyan
    & $vadDownload "silero-v6.2.0" $ModelDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Silero VAD model download failed with exit code $LASTEXITCODE."
    }
    Assert-DownloadedFile (Join-Path $ModelDirectory "ggml-silero-v6.2.0.bin") 1000000 "Silero VAD model"

    Download-File "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx" (Join-Path $KokoroDirectory "kokoro-v1.0.onnx") 100000000
    Download-File "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin" (Join-Path $KokoroDirectory "voices-v1.0.bin") 1000000
}

Write-Host ""
Write-Host "Voice assets are installed. Voice mode is still disabled." -ForegroundColor Green
Write-Host "Review the SHA256 values above and keep them with your local asset records."
Write-Host "Open V Settings > Voice to confirm the executable and model paths."
Write-Host "This installer did not start whisper-server, record audio, or enable wake-word listening."
