#requires -Version 5.1
[CmdletBinding()]
param(
    [int]$BuildThreads = 4,
    [switch]$SkipWhisperBuild,
    [switch]$BuildWhisperCuda,
    [switch]$SkipModelDownloads
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WhisperSource = Join-Path $ProjectRoot "apps\whisper.cpp"
$WhisperBuild = Join-Path $WhisperSource "build"
$WhisperCudaBuild = Join-Path $WhisperSource "build-cuda"
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
        [string]$Description,
        [string]$ExpectedSha256
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not downloaded: $Path"
    }
    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt $MinimumBytes) {
        throw "$Description is unexpectedly small ($($file.Length) bytes): $Path"
    }
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    if ($ExpectedSha256 -and $hash.Hash -ne $ExpectedSha256) {
        throw "$Description SHA256 mismatch. Expected $ExpectedSha256, received $($hash.Hash): $Path"
    }
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

if ((-not $SkipWhisperBuild) -or $BuildWhisperCuda) {
    Assert-Command "git"
    Assert-Command "cmake"

    # Environment variable names containing parentheses must use the .NET
    # accessor or PowerShell's braced variable syntax.
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles")
    $vswhereCandidates = @()
    if ($programFilesX86) {
        $vswhereCandidates += Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
    }
    if ($programFiles) {
        $vswhereCandidates += Join-Path $programFiles "Microsoft Visual Studio\Installer\vswhere.exe"
    }
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
    }

    # Pin the resolved commit, not just the human-readable tag name.
    # v1.9.5 is an annotated tag that resolves to this commit.
    $whisperCommit = (& git -C $WhisperSource rev-parse HEAD 2>$null).Trim()
    if ($whisperCommit -ne "d1be6fde11ac6e0407606b4e42fe72d34add8037") {
        throw "Existing whisper.cpp checkout is not the pinned v1.9.5 commit. Expected d1be6fde11ac6e0407606b4e42fe72d34add8037, received '$whisperCommit'. Remove or rename '$WhisperSource' before installing this pinned build."
    }

    if (-not $SkipWhisperBuild) {
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
}

if ($BuildWhisperCuda) {
    $msvcRoot = Join-Path $installation "VC\Tools\MSVC"
    $msvcToolset = Get-ChildItem -LiteralPath $msvcRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "14.38*" } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if (-not $msvcToolset) {
        throw "MSVC 14.38 was not found under $msvcRoot. Install the v14.38-17.8 x64/x86 build tools component, then retry."
    }
    $cudaRoot = [Environment]::GetEnvironmentVariable("CUDA_PATH")
    if (-not $cudaRoot -or -not (Test-Path -LiteralPath $cudaRoot -PathType Container)) {
        throw "CUDA_PATH is missing or invalid. Set CUDA_PATH to the CUDA 12.8 Toolkit directory, then reopen PowerShell."
    }
    $cudaCompiler = Join-Path $cudaRoot "bin\nvcc.exe"
    $cudaCublas = Join-Path $cudaRoot "lib\x64\cublas.lib"
    if (-not (Test-Path -LiteralPath $cudaCompiler -PathType Leaf)) {
        throw "CUDA compiler was not found: $cudaCompiler"
    }
    if (-not (Test-Path -LiteralPath $cudaCublas -PathType Leaf)) {
        throw "CUDA cuBLAS import library was not found: $cudaCublas"
    }

    Invoke-Native "cmake" @(
        "-S", $WhisperSource,
        "-B", $WhisperCudaBuild,
        "-G", "Visual Studio 17 2022",
        "-A", "x64",
        "-T", "version=14.38",
        "-DWHISPER_BUILD_SERVER=ON",
        "-DWHISPER_BUILD_EXAMPLES=ON",
        "-DWHISPER_BUILD_TESTS=OFF",
        "-DGGML_CUDA=ON",
        "-DCMAKE_CUDA_ARCHITECTURES=75",
        "-DCUDAToolkit_ROOT=$cudaRoot",
        "-DCMAKE_CUDA_COMPILER=$cudaCompiler"
    ) "Configure CUDA whisper.cpp server for RTX 2060 Super (sm_75)"

    Invoke-Native "cmake" @(
        "--build", $WhisperCudaBuild,
        "--config", "Release",
        "--target", "whisper-server",
        "--parallel", "$BuildThreads"
    ) "Build CUDA whisper-server"

    $cudaServerCandidates = @(
        (Join-Path $WhisperCudaBuild "bin\Release\whisper-server.exe"),
        (Join-Path $WhisperCudaBuild "bin\whisper-server.exe")
    )
    $cudaServerPath = $cudaServerCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $cudaServerPath) {
        throw "CUDA build completed but whisper-server.exe was not found under $WhisperCudaBuild."
    }
    Write-Host "CUDA Whisper server: $cudaServerPath" -ForegroundColor Green
    Write-Host "In V Settings > Voice, set Whisper server path to this CUDA executable." -ForegroundColor Yellow
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
    Assert-DownloadedFile (Join-Path $ModelDirectory "ggml-silero-v6.2.0.bin") 800000 "Silero VAD model" "2AA269B785EEB53A82983A20501DDF7C1D9C48E33AB63A41391AC6C9F7FB6987"

    Download-File "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx" (Join-Path $KokoroDirectory "kokoro-v1.0.onnx") 100000000
    Download-File "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin" (Join-Path $KokoroDirectory "voices-v1.0.bin") 1000000
}

Write-Host ""
Write-Host "Voice assets are installed. Voice mode is still disabled." -ForegroundColor Green
Write-Host "Review the SHA256 values above and keep them with your local asset records."
Write-Host "Open V Settings > Voice to confirm the executable and model paths."
Write-Host "This installer did not start whisper-server, record audio, or enable wake-word listening."
