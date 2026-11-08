# Phase 4 — Integrated Multimodal Interaction

**Status:** In progress  
**Objective:** Make text, voice, and visual input parts of one coherent interaction system, with shared conversation state, natural turn-taking, explicit sensor controls, and local processing.

## 1. Intended result

V should communicate through text and local speech, listen when authorized, interrupt or be interrupted naturally, and interpret user-authorized visual observations. These modalities must share identity, memory, and functional state rather than behave like separate assistants.

## 2. Existing foundation and code audit

The active branch already implements a PySide6 desktop application, a dedicated runtime thread with an asyncio event loop, local LM Studio chat, local Whisper.cpp speech recognition with Silero VAD, local Kokoro ONNX synthesis, explicit push-to-talk capture, in-memory audio handling, queued playback, streamed text segmentation, stale speech interruption on new turns/conversation changes, and user-triggered audio device discovery.

The audit confirms these components should be reused rather than replaced. The current interaction lifecycle is still split across the desktop service, Qt runtime thread, recorder, speech synthesizer, and player. Voice transcripts are passed into the ordinary chat method as text, but there is no shared typed event/provenance object connecting the source modality, capture time, receipt time, consent path, and derived transcript.

The documented and inspected gaps remain wake-phrase/continuous listening, automatic barge-in while V speaks, voice audition, and webcam/vision. The existing push-to-talk recorder opens the microphone only after an explicit user action and stores captured audio in memory. Preserve that privacy baseline.

## 3. Shared multimodal interaction model

A modality-neutral event contract is now introduced in `src/v/interaction/events.py`.

The immutable `InteractionEvent` records:
- Event kind and source modality.
- Timezone-aware source/capture time and runtime receipt time.
- Conversation association when applicable.
- Explicit activation/consent context.
- Derived text separately from an optional source reference.
- Optional confidence and non-sensitive string metadata.

The event contract never stores raw audio or image bytes. A transcript is not the original audio. A generated visual description is not the image. Preserve these distinctions in provenance.

The desktop service now creates typed-message events and push-to-talk transcript events. Both enter the same `send_message` generation, memory, cognition, and persistence path. The runtime thread emits each event through `interaction_event_received`; the service also retains a bounded in-memory buffer of the latest 100 events. Voice events distinguish when the WAV reached the service from when local transcription completed. No raw WAV bytes are included in events. This is runtime provenance, not yet durable event-history storage.

Initial event kinds cover typed messages, speech transcripts, visual observations, camera snapshots, playback lifecycle, interruption, cancellation, timeout, and sensor-state changes. Unit tests validate timestamp ordering, timezone awareness, confidence bounds, immutability, and unique event IDs.

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

1. **Audit existing runtime and media components — completed.** Reuse the current local voice stack; no replacement STT/TTS pipeline is planned.
2. **Define modality-neutral event and provenance contracts — implemented.** The shared immutable event model and validation tests exist.
3. **Integrate typed and spoken turns through one conversation lifecycle — initial implementation added.** Typed messages and push-to-talk transcripts now use the same chat pipeline; event provenance is available to the Qt runtime and retained in a bounded in-memory buffer. Automated tests cover modality, activation path, conversation association, and transcript flow. Durable event storage and target-PC runtime verification remain outstanding.
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
