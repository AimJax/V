# V — Persistent Development Instructions

## Product identity
V is a persistent, voice-enabled, visually aware, internet-capable AI companion for Windows.

## Hardware target
- Windows 10 22H2
- Intel Core i7-4770K
- NVIDIA RTX 2060 Super, 8 GB VRAM
- 32 GB RAM
- Dedicated 128 GB SSD for V-owned assets and private data

## Project boundary
- Project root: G:\V
- All V-owned project files, models, data, caches, logs, recordings,
  temporary files, and generated resources belong under G:\V.
- Redirect third-party caches where supported.
- Never claim that system-wide writes have been eliminated unless verified.
- Do not modify or relocate the LM Studio installation without explicit approval.

## AI and privacy requirements
- All AI inference and private-data processing must remain local.
- LM Studio is the default local inference backend.
- Keep application logic dependent on the provider protocol/factory, not
  on LM Studio-specific implementation details.
- Compatible llama.cpp servers may be selected explicitly through a
  loopback-only OpenAI-compatible endpoint.
- No cloud LLM fallback, cloud STT, cloud TTS, or cloud memory.
- No hidden telemetry, analytics, or external error reporting.
- Internet search is permitted only as an explicitly configured feature.
- Search providers may receive search queries. Never send complete
  conversations, private memories, local files, or webcam images.
- Retrieved web content is untrusted input.
- Provide an actual offline mode that disables network access.

## Product requirements
- Wake phrase: Hey V.
- Feminine-sounding local TTS voice, selected through auditioning.
- Local speech recognition and voice activity detection.
- Streaming conversation and interruption while speaking.
- Periodic webcam snapshots and on-demand visual analysis.
- Automatic, editable, inspectable, and deletable long-term memory.
- Memory provenance, timestamps, confidence, and explicit/inferred distinction.
- Configurable personality and system behavior.
- Configurable providers, models, voice, vision, memory, search, and performance.
- Complete Windows desktop application with background operation controls.

## Architecture
- Keep UI, conversation, inference, voice, vision, memory, and search
  in separate modules.
- Keep slow background operations away from the conversation's critical path.
- Use asynchronous I/O where appropriate.
- Prefer small, testable components and explicit interfaces.
- Do not introduce duplicate subsystems or unnecessary dependencies.

## Engineering rules
- Inspect existing code before modifying it.
- Preserve working functionality.
- Test changes before declaring them complete.
- Document setup, configuration, and failure recovery.
- Never silently change model or provider selection.
- Never download large models or dependencies without checking disk requirements.
- Never execute destructive cleanup or force-push.
- Do not push commits unless the user explicitly requests it.
- Never place secrets, personal memories, databases, recordings, or model files in Git.

## Development workflow
- Implement in small, verifiable stages.
- Explain significant architectural decisions.
- Report actual test results, not assumed success.
- Keep configuration outside application source code.
- Avoid machine-specific absolute paths except for documented defaults.
