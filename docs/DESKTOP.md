# V Desktop Application

## Initial desktop milestone

The first desktop interface is a native Qt Widgets application built with the official PySide6 bindings.

- The Qt interface runs on the main GUI thread.
- The async inference, conversation persistence, semantic retrieval, and memory extraction runtime runs in a dedicated QThread with its own asyncio event loop.
- Chat uses the configured LM Studio model and the same local conversation and memory databases as the CLI.
- Conversation history is restored from SQLite and can be switched from the recent-session list.
- The Settings dialog configures the loaded chat model, generation parameters, personality instructions, memory behavior, and offline-mode policy.
- Settings are saved as local overrides in `config/local.toml` using TOML round-trip editing so unrelated local values and comments are preserved. The personality file is saved separately under the project directory.
- Settings changes require an application restart. The current runtime is not hot-reconfigured after saving.
- Disabling strict offline mode does not activate web access; search and retrieval are not connected to the desktop application yet.
- The Memory Manager searches and filters records by content, memory type, and provenance.
- Memory content, subject, type, key, confidence, importance, and supporting evidence can be corrected while original source references are retained.
- Permanent memory deletion requires confirmation and explicitly notes that conversation-history and backup copies are separate.
- Memory JSON export and merge-only import are available from the manager, with plaintext and overwrite warnings.
- Memory database operations are routed through the runtime thread rather than the Qt GUI thread.
- The desktop service does not start cloud inference, telemetry, or external error reporting.
- The Voice settings tab configures local Whisper.cpp, Silero VAD, and Kokoro ONNX assets.
- Voice mode is disabled by default. With the asset files installed and voice explicitly enabled, the chat composer exposes a Hold to talk control. The microphone is opened only while the user holds that control; captured audio is kept in memory and converted to 16 kHz mono WAV before local transcription.
- Whisper.cpp runs as a separate local process bound to 127.0.0.1. Silero VAD is applied by Whisper.cpp before transcription. The server is started lazily on the first push-to-talk utterance and stopped when V closes.
- When Speak replies is enabled, V warms Kokoro in a background worker and segments Gemma's streamed text into speakable phrases. Kokoro synthesizes audio chunks asynchronously on CPU while Gemma continues generating; the Qt player queues them in order. Speech synthesis never delays text completion, and a TTS failure does not discard the response. Starting a new turn, switching conversations, or pressing push-to-talk interrupts stale queued speech. CPU synthesis deliberately leaves the limited 8 GB GPU memory available for the chat and embedding models.
- Audio device discovery is user-triggered from Settings > Voice > Refresh devices. Opening Settings does not open or record from the microphone.
- Wake phrase detection (including continuous “Hey V” listening), automatic voice-activity barge-in, voice audition, and webcam/vision are not implemented in this milestone. Pressing push-to-talk manually interrupts current speech.
- The CLI remains available independently of the optional desktop dependency.

## Install and launch

From PowerShell:

```powershell
& "G:/V/.venv/Scripts/python.exe" -m pip install -e ".[desktop]"
& "G:/V/.venv/Scripts/python.exe" -m v desktop
```

LM Studio must be running with the configured model loaded before V starts. The GUI reports a local connection error instead of choosing another provider or model.

## Qt / Windows compatibility

The optional dependency is constrained to `PySide6>=6.11,<6.13`. Qt 6.12 is the final Qt release line supporting Windows 10; Windows 10 22H2 is within the documented Windows 10 1809-or-later support range. This upper bound prevents a future Qt 6.13 upgrade from silently dropping the target OS.

## Optional voice setup

The voice runtime is optional and does not affect text-only use. Voice assets are stored under ignored project folders.

1. Install the optional Kokoro ONNX dependency into V's Python 3.13 environment:

   ```powershell
   & "G:/V/.venv/Scripts/python.exe" -m pip install -e ".[voice]"
   ```

2. Ensure Git, CMake, and Visual Studio 2022 Build Tools with the Desktop development with C++ workload are installed.
3. Run the pinned local asset installer from PowerShell:

   ```powershell
   Set-Location G:\V
   .\scripts\install_voice_assets.ps1
   ```

   The script clones whisper.cpp v1.9.5, builds the CPU whisper-server, and downloads the multilingual Whisper Small model (`ggml-small.bin`, approximately 466 MB), Silero VAD v6.2.0, and Kokoro ONNX model/voices files. It prints SHA-256 values for downloaded assets. It does not start the server or activate the microphone.

   If the CPU and CUDA servers are already built and you only need the Whisper model, skip the builds:

   ```powershell
   Set-Location G:\V
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install_voice_assets.ps1" -SkipWhisperBuild
   ```

   Existing VAD and Kokoro assets are reused when already present.

   To also build the optional CUDA server for an NVIDIA GPU, run the installer with `-BuildWhisperCuda`. The CUDA build targets architecture 75 (RTX 20-series), uses the configured CUDA Toolkit and MSVC toolset, and is written separately under `apps/whisper.cpp/build-cuda`. The installer prints the resulting executable path. The CPU build remains available as an independent fallback.

4. Open Settings > Voice, press **Refresh devices**, and confirm the microphone and output device. Choose **CPU** or **NVIDIA GPU (CUDA)** under **Speech recognition device**. Set the CPU and CUDA Whisper executable paths to the corresponding build outputs; set **Whisper model (multilingual)** to `models/whisper/ggml-small.bin`. Only the selected backend must exist to enable voice. Enable **Enable local voice interaction (push-to-talk)**. Enable **Speak V's replies** only when the Kokoro ONNX model and voices file are present. Save settings and restart V.

The voice implementation supports explicit push-to-talk only. It sends audio through the selected local Whisper.cpp backend and Silero VAD, then the existing Gemma chat and memory pipeline. Choose CPU for the CPU-only executable or NVIDIA GPU (CUDA) for the CUDA-enabled executable. V does not silently fall back between them: if the selected executable is missing or fails to start, transcription reports an error. Optional replies are spoken with Kokoro ONNX and played from memory without writing audio to disk.

## Current scope

The desktop application currently provides persistent local chat, streaming responses, recent conversation switching, local model status, memory management, editable settings, and optional explicit push-to-talk with local STT/TTS.

The wake phrase “Hey V”, always-on wake-word listening, barge-in while V speaks, voice audition, webcam/vision, tray/background controls, packaging, and installer work remain future stages.
