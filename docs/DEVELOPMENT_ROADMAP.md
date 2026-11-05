# V Development Roadmap

**Status:** Living implementation plan  
**Target branch:** `network-policy-and-offline-mode`

This roadmap defines the remaining work to develop V into a coherent, persistent, multimodal companion. It is a plan, not a claim that every capability exists.

## Product direction

V should have a stable identity and continuity across conversations, restarts, and model changes. Her behavior should arise from persistent identity, accumulated experience, functional internal state, contextual judgment, and integrated interaction—not only from a system prompt or disconnected features.

The governing product direction is [Product Philosophy](PRODUCT_PHILOSOPHY.md).

## Current baseline

The active branch already contains local LM Studio inference, persistent conversations, configurable personality instructions, a substantial SQLite memory system, memory review/backfill and evidence provenance, hybrid retrieval, a Windows desktop application, local Whisper.cpp/VAD speech recognition, Kokoro speech synthesis, and application-level network/offline policy.

The branch documentation identifies gaps including a dedicated persistent identity domain, a complete cognitive/affective architecture, integrated vision, wake-phrase listening, and bounded initiative/background activity. Every phase must begin with a code-level audit; do not duplicate existing functionality.

## Phase sequence

| Phase | Name | Outcome |
|---|---|---|
| 1 | [Persistent Identity](PHASE_1_PERSISTENT_IDENTITY.md) | Versioned identity independent of prompts, models, sessions, and memory |
| 2 | [Memory and Continuity](PHASE_2_MEMORY_AND_CONTINUITY.md) | Evidence-linked autobiographical continuity and contextual recall |
| 3 | [Cognitive and Affective Architecture](PHASE_3_COGNITIVE_AFFECTIVE_ARCHITECTURE.md) | Functional appraisal, affect, motivation, preferences, and reflection |
| 4 | [Integrated Multimodal Interaction](PHASE_4_MULTIMODAL_INTERACTION.md) | Text, voice, and vision as one consent-based interaction system |
| 5 | [Initiative and Bounded Autonomy](PHASE_5_INITIATIVE_AND_AUTONOMY.md) | Contextual proactive conversation and safe background work |

The sequence reflects dependencies. Later phases must not bypass contracts established by earlier phases.

## Cross-phase engineering constraints

- **Local-first:** Chat, memory, embeddings, STT, TTS, vision, and private-data processing remain local. No cloud AI fallback or silent provider/model switching.
- **Hardware-aware:** Target RTX 2060 Super 8 GB VRAM and 32 GB RAM. Use lazy loading, resource arbitration, and CPU execution where appropriate; do not assume multiple specialist models can remain resident.
- **Privacy:** No hidden telemetry or undisclosed recording. Never send private conversation, memory, local files, or webcam images to search providers.
- **Offline mode:** Preserve the existing network policy. Offline mode blocks external access without disabling local inference.
- **Honesty:** Distinguish memory, observation, inference, speculation, and unknown information. Do not fabricate off-screen activity or subjective experience.
- **User control:** Provide controls for sensors, memory, retention, proactive behavior, and external actions. Consequential actions require explicit authorization.
- **Security:** The model is not a security boundary. Permissions and network/filesystem restrictions must be enforced by application code.
- **Compatibility:** Preserve existing data with explicit, tested migrations and backward-compatible imports.
- **Reliability:** Background work must be bounded, cancellable, observable, and unable to block interactive chat.
- **Verification:** A phase is not complete until its acceptance criteria, privacy behavior, failure handling, migrations, and automated tests pass.

## Definition of project completion

The planned development is complete when all five phases are verified and:

- Identity survives restarts and model/provider changes.
- Memory preserves evidence, chronology, uncertainty, corrections, and useful continuity.
- Functional affect and motivation influence behavior in bounded, explainable ways without claims of consciousness.
- Text, voice, and visual observations share context with timestamps, consent, and provenance.
- Proactive behavior is configurable, quiet-hours-aware, rate-limited, interruptible, and safe.
- Offline/local-only guarantees and permission enforcement are tested.
- Existing user data survives upgrade and recovery procedures are documented.
- Unit, integration, migration, failure-mode, and multi-session tests pass on the supported Windows environment.
- No known critical privacy, security, data-loss, or interaction-blocking defect remains.

## Status definitions

- **Planned** — specified but not implemented.
- **In progress** — implementation has started.
- **Implemented, unverified** — code exists but acceptance criteria are not fully verified.
- **Verified** — acceptance criteria and required tests pass on target hardware/OS.
- **Blocked** — a named dependency or decision prevents safe progress.

Do not mark a phase verified based only on documentation, mocked tests, or a single successful demonstration.
