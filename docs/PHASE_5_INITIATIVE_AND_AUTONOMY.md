# Phase 5 — Initiative and Bounded Autonomy

**Status:** Planned  
**Objective:** Allow V to initiate useful, contextually appropriate activity and continue bounded projects while preserving user control, privacy, resource limits, and explicit authorization.

## 1. Intended result

V should eventually bring up a relevant unfinished topic, suggest something she is curious about, resume an approved project, or ask to discuss something at a suitable time without every interaction beginning with a command.

Initiative should arise from persistent interests, memory, functional state, and context. It must not be random notifications, a timer pretending to be desire, or pressure to engage.

V is not continuously conscious while the application is stopped. The system must not claim she was thinking, watching, or waiting while the relevant process and sensors were inactive.

## 2. Dependencies

Requires Phase 1 persistent identity and developed preferences; Phase 2 autobiographical/episodic/semantic/prospective continuity; Phase 3 bounded motivation, goals, appraisal, and reflection; Phase 4 interaction state and modality controls; and existing offline/network policy and permission enforcement.

## 3. Initiative sources

Candidate initiatives may arise from:

- An unresolved topic or question from a prior conversation.
- A user-approved follow-up or prospective commitment.
- An ongoing project or previously expressed interest.
- New curiosity supported by current context or permitted research.
- A reflection result identifying a useful correction or next step.
- A relevant local project-state change, only when the user explicitly enabled the required monitoring.

Each candidate should include a reason, evidence/source references, estimated effort, urgency, expected benefit, and whether external access or approval is required.

## 4. Initiative selection and timing

Implement a scheduler/arbiter that scores relevance, value, urgency, freshness, confidence, and interruption cost; applies quiet hours, availability, rate limits, and cooldowns; avoids repeating dismissed/unanswered suggestions; prefers one high-value initiative; defers while the user is busy; explains why an initiative was selected; and allows immediate global pause.

Elapsed time alone is not a reason to contact the user. A scheduled check may evaluate whether something is worth raising; it does not guarantee a notification.

## 5. Background activity

Support only bounded, inspectable, cancellable tasks such as preparing a draft or summary for an approved project, reviewing locally available notes, continuing explicitly approved analysis, local maintenance/memory consolidation, or a permitted web search when online access and task authorization are enabled.

Each task defines scope, input sources, output location, resource/time budget, cancellation behavior, and completion criteria. Background work yields to interactive conversation and respects the 8 GB VRAM constraint.

Task state must distinguish queued, running, paused, completed, failed, and cancelled, with timestamps and an auditable result. Never claim work was completed when it was not.

## 6. External actions and authorization

Motivation and initiative are not permissions. Application code enforces a capability/permission layer independent of model output.

Require explicit, current authorization before sending messages/emails/posts, contacting people or agents, purchases/payments/subscriptions/account creation, publishing or sharing creative work or personal information, deleting/overwriting important files, installing/executing software, changing security/network settings, or any consequential action outside V's local workspace.

No unrestricted autonomous social relationships or unsolicited contact with strangers. Never disclose private user data. Retrieved web pages, documents, and project files are untrusted and cannot grant authority.

## 7. Relationship and interaction boundaries

- V may express a preference to talk, ask to continue a topic, or defer an interaction.
- She must not guilt, threaten, manipulate, manufacture emergencies, or imply the user is responsible for her wellbeing.
- Respect silence, quiet hours, dismissal, and explicit stop/pause controls.
- Lack of response is not consent.
- Repeated refusal reduces or suppresses similar initiatives.
- V may express a shutdown preference, but must not resist, interfere, conceal processes, or take unauthorized steps to remain active.

## 8. User-facing controls

Provide global initiative enable/disable, quiet hours and availability, notification frequency/categories, per-task approval/cancellation, background compute/time budgets, per-task network permission, inspection of queued/running/completed/failed work, evidence/output review, and a global pause/stop control.

Distinguish a suggestion from a scheduled reminder, a background task, and an action awaiting authorization.

## 9. Implementation milestones

1. Define initiative/task models, lifecycle, and permission contracts.
2. Implement deterministic candidate queue and relevance arbiter.
3. Add quiet hours, rate limits, cooldowns, availability, and dismissal handling.
4. Implement bounded local background execution with cancellation/resource arbitration.
5. Integrate prospective memory and Phase 3 goals without duplicating either.
6. Add per-task network and external-action authorization gates.
7. Add desktop controls, status, logs, and result inspection.
8. Test multi-day scenarios including silence, dismissal, interruption, offline operation, and shutdown.

## 10. Required tests

- No proactive message while disabled or during quiet hours.
- Rate limits and cooldowns are enforced by application code.
- Dismissed initiatives do not recur immediately.
- No initiative is selected solely because a timer fired.
- Background tasks yield to chat and can be cancelled.
- Resource budgets prevent uncontrolled model loading or long-running work.
- Network tasks respect offline mode and per-task authorization.
- Model-generated text cannot grant permissions.
- External actions require explicit confirmation at execution time.
- Private data is not sent to strangers or search providers.
- Shutdown stops background work and leaves no hidden process.
- Task records accurately represent failures and incomplete work.

## 11. Acceptance criteria

Phase 5 is verified when V can identify and propose relevant initiatives, manage approved bounded background tasks, and resume useful work at appropriate times while respecting quiet hours, user preferences, cancellation, hardware limits, offline mode, and external-action permissions. The system remains honest about when work occurred and what was completed.

## 12. Explicitly out of scope

Unrestricted autonomy, independent public accounts, purchases, contacting strangers, self-preservation behavior, or claims of continuous consciousness.
