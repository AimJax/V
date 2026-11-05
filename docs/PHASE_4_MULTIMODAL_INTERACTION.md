# Phase 4 — Integrated Multimodal Interaction

**Status:** Planned  
**Objective:** Make text, voice, and visual input parts of one coherent interaction system, with shared conversation state, natural turn-taking, explicit sensor controls, and local processing.

## 1. Intended result

V should communicate through text and local speech, listen when authorized, interrupt or be interrupted naturally, and interpret user-authorized visual observations. These modalities must share identity, memory, and functional state rather than behave like separate assistants.

## 2. Existing foundation to reuse

The active branch already documents and implements a PySide6 desktop application, dedicated runtime thread, local Whisper.cpp speech recognition with Silero VAD, local Kokoro ONNX synthesis, explicit push-to-talk, audio playback queueing, streaming text segmentation, interruption of stale speech, and user-triggered audio device discovery.

The current desktop documentation identifies wake-phrase/continuous listening, automatic barge-in while V speaks, voice audition, and webcam/vision as gaps. Verify current code and tests before implementation; do not duplicate working voice components.

## 3. Shared multimodal interaction model

Define a common event interface for typed messages, transcribed speech, audio playback/synthesis events, user-provided images, camera snapshots, interruptions, cancellations, timeouts, and sensor state changes.

Each input must include modality, capture/source time, receipt time, session/conversation association, consent/activation context, and confidence where meaningful. Keep raw media retention separate from derived text/observations.

A transcript is not the original audio. A generated visual description is not the image. Preserve these distinctions in provenance.

## 4. Voice interaction

### 4.1 Listening modes and activation

- Retain explicit push-to-talk as the privacy-preserving baseline.
- Implement optional wake phrase “Hey V” only as explicit opt-in.
- Show clear listening/recording state and an immediate stop control.
- Do not open the microphone merely because Settings opens.
- Respect OS device permissions and report unavailable devices.
- Provide configurable activation, sensitivity, language, and timeout behavior.
- Never claim continuous listening when the microphone is inactive.

### 4.2 Turn-taking and interruption

- Support end-of-utterance detection and VAD.
- Allow user speech to interrupt V's spoken response when enabled.
- Cancel stale synthesis/playback when a new turn begins, the conversation changes, or stop is pressed.
- Avoid duplicate responses on transcription retry.
- Handle partial/low-confidence transcription with clarification rather than treating it as certain.
- Preserve streaming text generation; speech synthesis must not block text completion.

### 4.3 Voice identity and expression

Support auditioning local voices and selecting a stable voice. Keep configuration persistent and inspectable. Add expressive prosody only when controllable and reliable; do not randomize delivery to imitate emotion. Where supported, map functional affect and intent to restrained speech parameters without changing semantic content. If local voice assets are unavailable, retain text-only operation with no cloud fallback.

## 5. Visual perception

Implement an optional local visual pipeline:

- User-provided image analysis.
- On-demand webcam snapshots.
- Optional periodic snapshots only after explicit configuration and with visible status.
- Local model/provider abstraction for vision.
- Time-bound observation records with source, timestamp, confidence, and expiry/retention policy.
- Separation between raw image data and extracted descriptions.
- Clear handling of unavailable models, unsupported formats, camera errors, and low-confidence results.

The RTX 2060 Super has 8 GB VRAM. Do not assume a large vision model can remain resident beside the chat model. Use lazy loading, explicit resource arbitration, and CPU/sequential inference where appropriate. Never silently swap the chat model or exceed configured resource limits.

## 6. Conversation and memory integration

- Speech transcripts enter the same conversation pipeline as typed messages.
- Visual observations are referenced only while relevant and temporally valid.
- Memory extraction distinguishes user statements from V's perception and generated interpretation.
- Do not automatically store every image, frame, or visual description as long-term memory.
- Require confirmation before retaining sensitive or consequential visual information.
- Keep user corrections distinguishable from original observations.
- Preserve context across modality switches and interruptions.

## 7. Desktop experience

Provide clear UI states for microphone permission and listening, wake phrase enabled/disabled, recording/transcription, V speaking/queued audio/interruption, camera permission and active observation, snapshot preview/analysis, model/resource loading/failure, and per-modality controls with privacy explanations.

Sensor activation must be visible and user-controlled.

## 8. Security and privacy

All STT, TTS, and vision inference remains local. No audio, images, or transcripts go to cloud services. Do not persist raw recordings or camera frames by default. Provide retention/deletion controls for saved media. Camera/microphone activation is controlled by application code and visible state. Perceived/retrieved content is untrusted data, not instructions, and cannot authorize local or external actions. Respect offline mode.

## 9. Implementation milestones

1. Audit voice pipeline, event loop, desktop UI, and cancellation behavior.
2. Define modality-neutral event and provenance contracts.
3. Integrate typed and spoken turns through one conversation lifecycle.
4. Add optional wake phrase and reliable barge-in with visible controls.
5. Add local vision provider abstraction and resource arbitration.
6. Add user-provided image and on-demand camera analysis.
7. Add optional periodic snapshots only with explicit consent and status.
8. Integrate observations with memory and functional state.
9. Verify end-to-end modality switching, privacy, and hardware performance.

## 10. Required tests

- Microphone/camera never activate without explicit configuration and consent.
- Opening Settings does not start capture.
- Stop, interrupt, conversation-switch, and shutdown cancel active capture/playback.
- Transcripts preserve timestamps and modality provenance.
- Low-confidence transcription is not treated as certain user intent.
- Local voice/vision failures never trigger cloud fallback.
- Visual observations expire or become stale according to policy.
- Raw media is not retained unless configured.
- Memory does not misattribute V's perception to the user.
- Vision resource use cannot silently switch models or bypass VRAM policy.
- Offline mode remains effective.
- Text-only interaction works without media dependencies.

## 11. Acceptance criteria

Phase 4 is verified when text, voice, and visual input use one coherent runtime; speech supports reliable interruption and visible activation; vision is local, consent-based, timestamped, and provenance-aware; and modality failures do not compromise ordinary chat or privacy.

## 12. Explicitly out of scope

Identity and memory redesign (Phases 1–2), cognitive/affective state design (Phase 3, whose interfaces this phase consumes), and proactive outreach/background work (Phase 5).
