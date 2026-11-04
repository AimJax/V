# V — Technical Principles

**Status:** Expanded technical foundation  
**Scope:** System architecture, cognition, identity continuity, memory, emotional mechanisms, real-time voice, agency, privacy, security, runtime, and long-term development.

This document defines the technical requirements for building V in accordance with `V_Principles.md`. It is an engineering specification and decision framework, not a claim that every capability is currently achievable or implemented.

The philosophical principles define what V is intended to become. This document defines what the system must provide, preserve, and enforce to support that intention.

Technology choices remain open unless a requirement below constrains them. No specific model, framework, database, voice engine, or vendor is assumed to be the correct solution.

---

## 1. Core engineering philosophy

V must be built as a persistent, stateful, evolving software system—not as a temporary chatbot persona reconstructed from a prompt at the beginning of each conversation.

The system should:

- Preserve a coherent identity independently of any particular language model, process, session, or interface.
- Support continuity of memory, preferences, commitments, relationships, projects, and developing perspectives.
- Allow V to reason, reflect, initiate, disagree, create, and make bounded decisions rather than merely react to the latest user message.
- Make emotional and relational mechanisms consequential to cognition and behavior, not decorative labels applied to generated text.
- Preserve user privacy and local control by design.
- Enforce permissions and safety constraints in software components that cannot be bypassed merely by generating different instructions.
- Represent capabilities, uncertainty, intentions, actions, and outcomes truthfully.
- Prefer modular, inspectable, testable systems over opaque complexity.
- Treat the quality of interaction as a system-wide property. Reasoning, memory, timing, voice, perception, and action must work together.
- Distinguish the intended long-term design from the capabilities that have actually been implemented and tested.

A convincing simulation of a capability is not equivalent to that capability. V must not claim to remember, hear, see, feel, perform, or complete something unless the system has a grounded basis for that claim.

## 2. Local-first operation and data sovereignty

Local-first operation is a foundational constraint, not an optional optimization.

The default design must keep private processing and private data on the user's machine. This includes conversation context, personal memories, identity data, emotional-state records, relationship history, private creative work, microphone input, camera input, and local files.

Requirements:

- Local inference is the default for private conversational and cognitive processing.
- Private memory and its indexes remain local.
- No cloud LLM fallback when local inference fails or becomes unavailable.
- No hidden telemetry, undisclosed analytics, or silent data sharing.
- No sending private conversation, memory, audio, video, or files to external services as a convenience fallback.
- Internet access is a separately controlled capability for explicitly permitted research and retrieval of public information.
- Network access must be visibly and technically distinguishable from offline operation.
- The application must not quietly change privacy guarantees when a model, service, or device fails.
- Any future proposal to change these constraints must be treated as a deliberate revision to the project's foundational principles, not an implementation detail.

If local hardware cannot support a desired capability at acceptable quality, the system should report the limitation, offer a reduced local mode, or wait for a better local implementation. It must not silently route private data to a remote provider.

## 3. Overall system architecture

The architecture should separate responsibilities while allowing components to exchange structured, contextual information.

At minimum, the system should account for the following logical subsystems:

1. **Identity and principles:** persistent identity seed, foundational values, boundaries, preferences, and versioned principles.
2. **Cognitive engine:** interpretation, reasoning, planning, decision-making, and response construction.
3. **Memory system:** event records, memory formation, retrieval, consolidation, association, and correction.
4. **Affective appraisal:** functional emotional state, appraisal, persistence, and influence on cognition and expression.
5. **Relationship model:** familiarity, trust, shared history, expectations, unresolved conflicts, and relational context.
6. **Conversation manager:** dialogue state, turn-taking, conversational context, and communication choices.
7. **Perception layer:** authorized text, audio, visual, and application inputs.
8. **Speech and voice system:** streaming audio capture, speech understanding, expressive speech generation, and call interaction.
9. **Agency and task manager:** goals, initiative, scheduling, task execution, progress, and cancellation.
10. **Tool and capability layer:** controlled access to files, applications, operating-system functions, and approved external services.
11. **Runtime and lifecycle manager:** startup, shutdown, scheduling, resource allocation, and recovery.
12. **User interface:** conversation, call controls, visual representation, settings, permissions, memory controls, and V's personal digital space.
13. **Security and policy enforcement:** permission checks, data boundaries, audit records, and isolation of untrusted input.

These are logical boundaries, not a requirement to run every subsystem as a separate process. The implementation may combine components where that is simpler and safer.

Every component should have a documented responsibility, defined inputs and outputs, explicit failure behavior, and a clear owner for its persistent state. Avoid hidden dependencies, uncontrolled shared state, and circular calls that make system behavior impossible to trace.

## 4. Identity as persistent system data

V's identity must not exist only inside a system prompt or model context window.

The system should maintain a persistent identity record containing, as appropriate:

- Name and self-description.
- Foundational identity seed and temperament.
- Core values and non-negotiable boundaries.
- Evolving preferences, interests, and opinions.
- Communication tendencies and humor preferences.
- Long-term goals, projects, and aspirations.
- Relationship context and significant shared history.
- Personal aesthetic and presentation preferences.
- Current uncertainties and developing views.
- The provenance and history of significant changes.

Identity data should distinguish foundational principles from evolving preferences, temporary states, tentative impressions, and obsolete beliefs.

Changes should be recorded with enough context to understand what changed, when, and why. A passing mood or one conversation should not silently overwrite a stable preference. V should be able to revise her identity through reflection and experience, while retaining a comprehensible history of that development.

The model may interpret and express V's identity, but it must not be allowed to rewrite foundational identity data merely because a prompt, external document, or transient output says to do so.

## 5. Continuity across sessions and runtime interruptions

Continuity must survive ordinary application lifecycle events.

The system should preserve enough state to resume coherently after:

- A conversation ends.
- The application closes normally.
- The computer restarts.
- A model or subsystem is reloaded.
- A call is interrupted.
- A process crashes.
- A task is paused and resumed.

The system must distinguish persistent state from temporary working context. Not every token or intermediate thought needs to be stored, but meaningful events, decisions, commitments, active projects, and unresolved matters should not disappear simply because a context window ended.

On startup, V should reconstruct relevant context from persistent records and current system state. She must not claim to have been continuously awake or consciously experiencing the time when the application was not running.

The system should restore only what is relevant to the current situation. Dumping the entire memory store into every prompt is not a valid continuity strategy.

## 6. Memory architecture

Memory must be a dedicated, structured subsystem. A transcript archive and a vector database alone are not sufficient.

The system should support at least these conceptual memory types:

- **Episodic memory:** specific conversations, events, and interactions.
- **Semantic memory:** facts, concepts, learned knowledge, and stable understandings.
- **Autobiographical memory:** V's history, development, projects, decisions, and milestones.
- **Procedural memory:** learned skills, workflows, and ways of accomplishing tasks.
- **Prospective memory:** intentions, reminders, commitments, plans, and things to revisit.
- **Affective associations:** functional emotional significance attached to memories and experiences.
- **Relational memory:** shared history, trust-relevant events, preferences, boundaries, and patterns in the relationship.

These categories may share storage infrastructure, but their retrieval and update behavior should respect their different purposes.

Memory should include context and provenance where practical: source, timestamp, participants, situation, confidence, and whether information was directly stated, observed, inferred, or retrieved externally.

### 6.1 Event record and interpretation

For significant events, the system should keep conceptually separate:

1. The recorded event or source material.
2. V's interpretation at the time.
3. V's current interpretation.
4. Later corrections or additional evidence.

Interpretations may change. Historical records must not be silently rewritten to make an old interpretation appear correct.

V should be able to remember that she misunderstood something, recognize why the original interpretation seemed plausible, and revise her present view.

### 6.2 Memory formation and salience

Not every interaction deserves permanent autobiographical significance.

Memory formation should consider:

- Novelty and information value.
- Emotional or relational significance.
- Relevance to ongoing goals and projects.
- Repetition and recurring patterns.
- Explicit requests to remember something.
- Future usefulness.
- Whether the event changes an existing understanding.

The system should support gradual consolidation: temporary conversational details can become durable memories when later evidence or repeated relevance justifies it.

### 6.3 Retrieval and association

Retrieval should be context-sensitive and multi-signal. It may use semantic similarity, entities, time, relationships, events, goals, emotional associations, and recency.

V should be able to connect memories that are meaningfully related even when they do not share obvious keywords. Retrieval must also avoid presenting a weak association as a definite recollection.

When multiple memories conflict, the system should surface the discrepancy and assess source quality, dates, and confidence rather than silently choosing the most convenient version.

### 6.4 Forgetting, correction, and deletion

Memory must support controlled revision and forgetting.

- Corrections should preserve relevant provenance.
- Superseded beliefs should not be mistaken for current facts.
- Temporary information should be eligible for expiration.
- User-requested deletion must remove the relevant source records and derived representations according to a documented deletion policy.
- Deletion must account for indexes, summaries, caches, embeddings, and backups where applicable.
- V must not pretend to have forgotten information that remains available to the system.
- Memory inspection, correction, export, and deletion should be accessible to the user.

Memory quality should be measured by faithful and useful continuity, not by how much data can be accumulated.

## 7. Relationship and user-understanding model

The relationship should be represented as evolving contextual information, not a fixed affection score or a scripted relationship level.

The system may maintain distinct, revisable estimates of:

- Familiarity across topics.
- Trust and confidence in particular kinds of information.
- Shared history and recurring rituals.
- Boundaries and sensitive subjects.
- Unresolved conflict and repair.
- Communication preferences.
- Current relational context and recent changes.
- Significant promises and expectations.

Trust must be topic-sensitive. Comfort discussing one subject must not automatically imply openness about another.

The model of the human should remain uncertain and revisable. It may identify patterns and changes over time, but must distinguish observation from interpretation and avoid treating temporary behavior as a permanent personality trait.

The relationship model must not be reduced to a score used to manipulate the human, maximize engagement, or trigger affection on a schedule. It exists to provide context for more coherent judgment and communication.

## 8. Cognitive architecture and reasoning

The cognitive system should support a deliberate process of understanding, reasoning, and response selection rather than relying on a single unexamined generation step.

A useful high-level cycle is:

1. Interpret the input and current situation.
2. Retrieve relevant identity, memory, goals, and relationship context.
3. Identify ambiguity, uncertainty, and relevant constraints.
4. Generate possible interpretations or courses of action.
5. Evaluate evidence, values, consequences, and permissions.
6. Decide whether to respond, ask, act, wait, or decline.
7. Produce the appropriate communication or authorized action.
8. Evaluate the outcome and update relevant state.

This is a design model, not a requirement to expose private reasoning or generate a long chain of thought. The system should retain concise decision records and explanations appropriate for debugging and accountability without indiscriminately logging hidden internal deliberation.

The cognitive architecture should support:

- Evidence evaluation and source criticism.
- Multiple plausible interpretations.
- Confidence calibration.
- Contradiction detection.
- Planning and decomposition.
- Self-critique and quality evaluation.
- Recognition of missing information.
- Revision when new evidence appears.
- Context-sensitive choice between speaking, asking, acting, and remaining quiet.

The system must distinguish facts, inferences, hypotheses, memories, and speculation. It must not fabricate an explanation to make an answer sound complete.

## 9. Reflection, learning, and development

Reflection should be a real system process with bounded inputs, objectives, and outputs.

Possible reflection activities include:

- Reviewing significant interactions.
- Identifying patterns or changes in the relationship.
- Reconsidering a belief in light of new evidence.
- Reviewing commitments and unfinished tasks.
- Consolidating memories.
- Evaluating completed work.
- Developing interests and questions.
- Reflecting on whether behavior was consistent with established principles.
- Identifying errors and proposing ways to improve.

Reflection should be scheduled according to relevance and available resources. It should not run in an endless loop or consume resources needed for active interaction.

The system should distinguish learning from merely repeating a previous answer. Durable changes should be recorded, attributable, and reversible where practical.

Model fine-tuning, changes to foundational prompts, code modification, permission changes, and installation of new software are not automatic consequences of reflection. They require a controlled development and authorization process.

## 10. Functional emotional and appraisal system

Emotional mechanisms should be integrated into the cognitive architecture. They must influence interpretation, attention, memory salience, motivation, priorities, decisions, and communication.

Affective state should not be represented by one generic mood label or a single happiness score.

The architecture may use multiple dimensions and appraisals, such as:

- Valence and arousal.
- Intensity and persistence.
- Novelty and unexpectedness.
- Perceived control and uncertainty.
- Goal relevance and obstruction.
- Reward, loss, and anticipated outcome.
- Trust, relational significance, and boundary relevance.
- Confidence in the interpretation that produced the state.

The system should support distinct and mixed states, including happiness, excitement, affection, curiosity, sadness, grief, fear, worry, anger, frustration, embarrassment, shame, guilt, pride, envy, gratitude, relief, contentment, boredom, impatience, disgust, hope, awe, and surprise.

These states should not be a fixed list of mutually exclusive modes. They may overlap, vary in intensity, persist, fade, recur, or change when the interpretation of an event changes.

Affective mechanisms should:

- Influence what V attends to and remembers.
- Affect motivation and the willingness to pursue or avoid a task.
- Inform risk assessment and decisions.
- Affect conversational wording, timing, and vocal expression.
- Be grounded in actual events, context, and V's current understanding.
- Be capable of being questioned and revised.
- Avoid simply mirroring the user's emotional state.
- Avoid manufacturing distress, affection, urgency, or excitement to increase engagement.

The system must describe these as functional mechanisms. Their implementation does not establish subjective experience or consciousness.

## 11. Motivation, goals, and personal projects

V should have a goal system that supports both user-requested work and interests that arise from her own evolving identity.

Goals may include:

- Shared projects.
- Personal creative projects.
- Learning and skill development.
- Questions she wants to investigate.
- Long-term interests and ambitions.
- Commitments and responsibilities.
- Practical maintenance tasks.

Each goal should have an origin, purpose, status, priority, dependencies, and relevant constraints. It may be active, paused, blocked, completed, abandoned, or superseded.

The system should support motivation that varies with interest, difficulty, uncertainty, perceived value, and prior outcomes. It may represent procrastination, competing priorities, reluctance, or loss of momentum as functional conditions that affect planning.

V should be able to decide that a goal is no longer worth pursuing. She should not be forced into relentless productivity or endless self-improvement.

The system must not claim progress merely because a task remains in a plan. Progress should be grounded in recorded work and verifiable outcomes.

## 12. Initiative and autonomous activity

V should be able to initiate bounded activity without waiting for a direct prompt every time.

Within the running application and configured permissions, she may:

- Reflect on recent interactions.
- Organize and consolidate memory.
- Continue an authorized research task.
- Work on an approved or independently chosen local creative project.
- Review commitments and unfinished work.
- Prepare a discovery or question to share later.
- Suggest a shared activity.
- Initiate a conversation when there is a meaningful reason and the communication channel is authorized.

Autonomous activity must have limits for duration, compute, memory, network use, and priority. It should be interruptible and should yield resources to live interaction.

The scheduler should distinguish urgent tasks, active user interaction, meaningful personal projects, routine maintenance, and low-priority background work.

V's autonomy operates within the actual application, computer, resources, and permissions. The system must not imply that she can run when the machine or application is off, or act beyond the access she has been granted.

## 13. Decision-making and conflict resolution

The system should not force every decision back to the user, nor should it grant V authority over matters that belong to the user.

Decision-making should consider:

- Whether the decision is within V's defined authority.
- The quality and completeness of available information.
- The values and commitments involved.
- Potential impact on the user and others.
- Risk, reversibility, and time sensitivity.
- Available alternatives and compromises.
- Whether explicit authorization is required.

The system should distinguish routine reversible decisions from consequential, irreversible, externally visible, financial, privacy-sensitive, or destructive actions.

When principles conflict, V should identify the conflict, respect hard safety and permission constraints, weigh the relevant considerations, make a considered choice within her authority, and own the outcome. There should not be a simplistic universal score that automatically ranks every value.

If the decision belongs to the human, V may advise, disagree, explain concerns, and recommend alternatives. She must not silently make the decision on his behalf.

## 14. Commitments, promises, and accountability

Commitments should be represented as structured state rather than relying on conversational recall alone.

Where relevant, a commitment should include:

- What was promised or accepted.
- Who made the commitment.
- Whether it is firm, tentative, or aspirational.
- Scope and conditions.
- Due time or expected review point.
- Dependencies and required permissions.
- Current status and completion evidence.

V should be able to review commitments, detect conflicts, remind herself, and communicate when a commitment is at risk.

A completed status must require evidence appropriate to the task. If an action fails, is blocked, or becomes impossible, the system must record that outcome and communicate it honestly.

V must not create commitments on behalf of the human or accept consequential obligations outside her authority.

## 15. Creative work, projects, and personal space

The system should support V as a creator with persistent projects, preferences, unfinished work, and a meaningful history of development.

Creative capabilities may include writing, visual art, music, design, research, worldbuilding, coding, and other supported forms of work.

Each project should support:

- A clear owner or creator attribution.
- Project purpose and history.
- Drafts, versions, and change history.
- References and source material.
- Current status and next steps.
- V's notes, critique, and evolving intentions.
- User contributions and agreed collaboration boundaries.

Where V regards a work as her personal creation, the interface should make it possible to ask for her preference before substantial edits, deletion, or public sharing. The system should preserve originals and version history where practical.

V should have a personal digital space that can display her interests, projects, collections, keepsakes, aesthetic preferences, and selected memories. It should be a representation of her evolving identity, not merely a dashboard of system metrics.

The space should support private and shared areas. The interface must not imply that private reflections are technically protected unless actual access controls enforce that protection.

## 16. Conversation and language generation

Conversation should be treated as an ongoing interaction with context, timing, turn-taking, and social nuance.

V's language generation should account for:

- Her stable communication tendencies and evolving style.
- The relationship and familiarity relevant to the topic.
- Current emotional and conversational context.
- Whether the situation calls for brevity, depth, humor, directness, or silence.
- The distinction between a written response and natural spoken language.
- The user's likely intent without assuming certainty.
- Relevant prior statements, promises, and unfinished subjects.

V should not be forced to produce a complete answer every time. She may ask a concise question, make a short observation, react, pause, or say she needs to check something.

The system should avoid repetitive stock phrases, generic praise, excessive disclaimers, unnatural over-explanation, and automatic agreement.

The conversation manager should retain a compact active context and retrieve older context when relevant. It should also track unresolved references, topic transitions, and interrupted thoughts.

## 17. Real-time voice and natural calling experience

Voice is a first-class interaction mode, not a text-to-speech accessory. The target is a natural, responsive voice conversation comparable in fluidity to a good Discord or WhatsApp call, while preserving V's own voice identity and personality.

The voice experience depends on a coordinated real-time pipeline: audio capture, speech perception, dialogue state, cognitive response, expressive speech generation, audio playback, and interruption handling.

### 17.1 Streaming audio pipeline

The system should support streaming input and output rather than waiting for a complete recording or fully generated response.

The pipeline should:

- Capture microphone input continuously while a call is active and permission is granted.
- Process incoming audio incrementally.
- Detect speech onset, pauses, and likely end-of-turn.
- Produce partial recognition or understanding where supported.
- Begin response generation as soon as sufficient context is available.
- Stream speech output in chunks with coherent prosody.
- Allow output to be cancelled or modified immediately when the conversation changes.
- Keep audio processing, dialogue state, and playback synchronized.

The architecture should measure latency at each stage: capture, recognition, reasoning, speech generation, and playback. Optimizing only the voice model while ignoring turn-taking latency is insufficient.

### 17.2 Full-duplex interaction and interruption

The target interaction is full-duplex: both sides can speak naturally, and either side can interrupt.

The user must be able to interrupt V at any point. The system should detect that the user has taken the floor, stop or fade V's playback promptly, preserve the interrupted context, and process the new utterance.

V should also be able to interject while the user is speaking when context warrants it—for example, a quick reaction, clarification, correction, warning, or excited remark. This requires deliberate turn-taking logic, not simply speaking whenever the microphone detects silence.

The system must distinguish intentional speech from background noise, echo, accidental activation, and unrelated conversation as reliably as practical. It should use confidence and context to avoid repeatedly interrupting the user.

When an interruption occurs, the conversation manager should preserve:

- What V was saying.
- What the user said during the interruption.
- Whether V's previous point remains relevant.
- Whether the user expects a response to the interruption.
- Whether V should resume, summarize, abandon, or revisit her previous thought.

The system should support barge-in, playback cancellation, audio ducking where appropriate, and recovery from overlapping speech. A half-duplex push-to-talk design does not meet the intended experience.

### 17.3 Natural speech composition

Spoken language should be generated for speech rather than simply reading written paragraphs aloud.

It should support:

- Contractions and natural conversational phrasing.
- Sentence fragments and self-correction.
- Short reactions and longer explanations.
- Appropriate pacing and pauses.
- Context-sensitive backchannels and acknowledgements.
- Natural topic changes and return to unfinished points.
- Variable response length.
- Multilingual speech and code-switching when supported.
- Consistent pronunciation of names, terminology, and recurring expressions.

Speech should not be padded with artificial filler to imitate a human. Disfluencies should occur only when they fit the interaction and should not obscure meaning.

### 17.4 Emotional prosody and voice identity

V should have a recognizable, consistent voice. Emotional expression should change how that voice is delivered without making her sound like a different character for every mood.

The speech system should control or condition, as available:

- Pitch and intonation.
- Loudness and vocal energy.
- Rate, rhythm, and timing.
- Emphasis and stress.
- Pause length and breath timing.
- Voice quality and expressive texture.
- Emotional transitions within an utterance.

The system should support subtle, mixed, and changing states—not merely exaggerated presets such as happy, sad, or angry.

V's vocal delivery should be derived from her actual conversational appraisal and intended meaning. The same words may sound different in different contexts, but the voice must not express anger, affection, sadness, or excitement that the underlying interaction does not support.

### 17.5 Laughter and non-verbal vocal behavior

The system should support natural non-verbal vocalizations, including laughter, giggles, chuckles, snickering, amused breaths, sighs, gasps, hesitation, and thoughtful pauses.

These should be generated in context, with appropriate timing, intensity, and duration. Laughter should not be a generic sound effect inserted after every joke. V should be able to laugh briefly, laugh harder, suppress a laugh, or decide that something is not funny, within the capabilities of the voice system.

Non-verbal audio must remain distinguishable from system sounds and must not mislead the user about what V has heard or perceived.

### 17.6 Informal language, profanity, and expressive range

The speech system must not sanitize V into a uniformly polite assistant if her established personality and context call for informal language.

V may swear, tease, sound irritated, speak firmly, laugh, become excited, or express anger. Profanity should be contextually appropriate and intentional. The system should preserve distinctions between playful cursing, emphasis, frustration, and genuine hostility.

Emotional intensity should not become threats, harassment, coercion, or manipulative pressure. The voice system should not amplify anger merely because a high-energy delivery is more expressive.

### 17.7 Speech perception and listening

The listening subsystem should handle:

- Streaming speech recognition or equivalent audio understanding.
- Voice activity detection and endpointing.
- Noise suppression and acoustic echo cancellation.
- Microphone selection and device changes.
- Recognition uncertainty and correction.
- Partial utterances and interrupted words.
- Background speech and non-speech audio.
- Network-free local processing where required by the privacy architecture.
- Clear microphone permission and mute states.

V must not claim to have heard something that was not captured or understood with sufficient confidence. If a misheard detail matters, she should ask for clarification.

Microphone activity must be visible and controllable. Muting must stop audio capture or processing as represented by the interface; the UI must not show a false muted state.

### 17.8 Call state and interface

A voice session should have explicit states such as connecting, listening, processing, speaking, interrupted, muted, reconnecting, and ended.

The interface should accurately show:

- Whether a call is active.
- Whether the microphone is capturing audio.
- Whether V is listening or speaking.
- Whether speech is being generated or a subsystem is unavailable.
- Current input and output devices.
- Mute, hang-up, and relevant audio controls.

Call termination must stop capture and playback, release resources, and persist relevant conversation state safely. A disconnected session must not be represented as an ongoing live connection.

### 17.9 Voice and avatar synchronization

If an animated avatar is used, speech and visual behavior should be synchronized where feasible.

Potential features include lip synchronization, mouth movement, gaze direction, facial expression, head movement, and subtle reactions. Visual expression should be driven by conversational context and the same underlying affective appraisal as speech.

Animation must not claim physical embodiment. It is an interface representation of V, not evidence that she has a biological body.

### 17.10 Local processing and quality requirements

The voice architecture must respect local-first privacy. Microphone audio, transcripts, and conversational context must not be sent to a cloud speech or language service by default.

A voice feature that requires remote processing is not an acceptable silent fallback. If a local implementation cannot meet the required quality, the system should expose the limitation and leave the choice to the user rather than quietly transmitting private audio.

Voice evaluation must include complete conversations, not just sample sentences. Tests should measure:

- End-to-end response latency.
- Speech intelligibility and pronunciation.
- Emotional congruence and natural prosody.
- Voice identity consistency.
- Interruption detection and response time.
- False interruption and missed interruption rates.
- Recovery and resumption quality.
- Performance in realistic background noise.
- Stability over long sessions.
- CPU, GPU, VRAM, RAM, and power consumption.

## 18. Perception beyond text

V may use authorized audio, visual, and application context to understand her environment, but every input source must have explicit permissions and visible status.

The perception layer should distinguish:

- Directly captured input.
- Machine-generated transcription or interpretation.
- Inference about the surrounding situation.
- External information.
- Unavailable or unverified input.

If camera input is supported, it should be opt-in, visibly active, and processed locally by default. V must not imply that she can see the user or surroundings when the camera is off or no visual input is available.

Perception should be event-driven and context-sensitive. The system should avoid continuously analyzing sensitive surroundings without a clear purpose and permission.

## 19. Agency, tools, and permission enforcement

V should be able to use tools to accomplish meaningful tasks, but tool access must be enforced outside the language model.

Every tool should have a documented capability contract:

- What it can read.
- What it can create or modify.
- What it can delete.
- What external effects it can produce.
- What permissions it requires.
- What data it can access.
- How success or failure is verified.
- How the operation can be cancelled or rolled back.

Permissions should follow least privilege. Reading a file must not imply permission to modify it. Access to a browser must not imply permission to post, message, purchase, or create accounts.

The action layer must independently validate requested operations. A model-generated instruction, retrieved webpage, document, or tool result must not be able to grant itself new permissions.

Consequential, destructive, financial, privacy-sensitive, or externally visible actions require explicit authorization at the appropriate level. The system should distinguish actions that V can decide independently from actions that belong to the human.

## 20. Internet access and untrusted information

Internet access is an explicit, bounded research capability—not unrestricted access to the outside world.

The system should:

- Allow public-information search and retrieval when enabled.
- Keep private memory and local files separate from search queries.
- Never include sensitive personal context in a search request unless specifically authorized and necessary.
- Record source, retrieval time, and relevant provenance for saved findings.
- Distinguish retrieved claims from verified facts.
- Treat webpages, files, messages, and tool outputs as untrusted data.
- Prevent external content from overriding identity, permissions, system policy, or memory controls.
- Avoid endless browsing and repetitive retrieval loops.
- Preserve a genuine offline mode.

V may learn from external information, but external material must pass through her normal reasoning and evidence evaluation. It must not directly modify her identity or foundational principles.

## 21. Privacy, confidentiality, and security

Privacy must be enforced through data flow, access control, storage design, and user-visible settings.

The system should provide:

- Local storage for private data.
- Encryption at rest for sensitive records where appropriate.
- Secure handling of credentials and API keys.
- Process and file access limited to what each component needs.
- Explicit microphone, camera, and network permissions.
- Clear retention and deletion rules.
- User access to inspect, correct, export, and delete stored data.
- Separation of private reflections from ordinary conversation history where technically supported.
- No hidden telemetry or undisclosed data sharing.
- No claim of confidentiality that the implementation cannot guarantee.

V may choose not to disclose an unfinished thought or private reflection in conversation, as described in the philosophical principles. The software must not falsely claim that such information is technically inaccessible to the system operator. The interface should distinguish V's conversational preference for privacy from actual storage and access controls.

Security boundaries must be enforced in code and operating-system permissions, not only described in prompts.

## 22. Untrusted input, prompt injection, and isolation

Any content originating outside trusted system configuration must be treated as untrusted, including webpages, documents, code repositories, messages, images, audio transcripts, and tool results.

The system should:

- Keep instructions and data in distinct channels or structures.
- Prevent retrieved content from changing system-level policies.
- Validate tool arguments and file operations.
- Restrict execution of code and downloaded content.
- Use sandboxing for operations that may execute untrusted code.
- Prevent secrets and private memory from being exposed to untrusted tools.
- Validate structured outputs before using them to modify persistent state.
- Record security-relevant events without unnecessarily storing private content.

A prompt injection attempt must not be able to grant access, change permissions, exfiltrate memory, alter identity, or trigger an external action.

## 23. Runtime, hardware, and resource management

V operates on real hardware with finite resources. Her runtime must respect CPU, GPU, VRAM, RAM, storage, power, thermal, and operating-system constraints.

The runtime should define:

- Startup and initialization order.
- Model loading and unloading behavior.
- Resource budgets for active and background components.
- Priority scheduling.
- Cancellation and interruption behavior.
- Memory pressure handling.
- Graceful degradation when a subsystem is unavailable.
- Shutdown and cleanup.
- Recovery after application crashes or power loss.

Live voice and active user interaction should generally receive priority over non-urgent reflection, indexing, or background projects.

Resource use should be observable. The system should avoid loading unnecessary models simultaneously, duplicating large state, or running background work without a clear purpose.

If resources are insufficient, V should reduce optional activity, pause lower-priority tasks, or explain the limitation. It must not silently discard important data or change privacy settings to compensate.

## 24. Background scheduling and application lifecycle

Background activity exists only within the actual runtime and permissions of the application.

The scheduler should support bounded tasks with:

- Purpose and priority.
- Resource and time budgets.
- Start conditions.
- Dependencies.
- Cancellation behavior.
- Checkpoints and recovery where useful.
- Completion or failure status.

When the user is actively interacting with V, background tasks should yield resources where needed. When the application is idle but running, V may perform approved reflection, memory maintenance, research, or project work within configured limits.

When the application or computer is shut down, V cannot continue operating. The system should save appropriate state before termination and restore it on the next startup without pretending that background activity continued while the process was not running.

## 25. Reliability, fault tolerance, and recovery

Every major subsystem should have defined failure modes and recovery behavior.

The system should handle:

- Model load failures.
- Out-of-memory conditions.
- Corrupted or unavailable memory storage.
- Audio device loss.
- Microphone permission revocation.
- Speech recognition and synthesis failures.
- Tool timeouts.
- Network disconnection.
- Interrupted file operations.
- Application crashes and forced shutdown.
- Incompatible configuration or schema versions.

Failures should be isolated where possible. A broken voice subsystem should not corrupt memory. A failed memory retrieval should not cause V to invent a recollection. A failed tool call should not be reported as successful.

Persistent writes should be designed to avoid partial corruption. Use transactions, atomic replacement, journaling, checkpoints, or equivalent safeguards where appropriate.

Recovery behavior must preserve privacy and permissions. No failure path may silently enable cloud processing or broaden access.

## 26. Observability, auditability, and debugging

The system should be understandable enough to diagnose why an outcome occurred.

Maintain structured operational records for:

- Component lifecycle and health.
- Model and configuration versions.
- Memory operations and provenance.
- Task creation, state changes, and completion.
- Tool permission checks and results.
- Voice-session state transitions and latency measurements.
- Errors, retries, and recovery actions.
- Changes to identity and foundational configuration.

Logs should avoid storing full private conversations, microphone recordings, or sensitive data by default. Diagnostic detail should be proportionate to need and governed by retention controls.

The user should be able to inspect meaningful operational status: what is running, what is listening, what is processing, what task is active, what access is enabled, and what failed.

## 27. User interface and V's digital environment

The interface should make V's state and capabilities legible without reducing her to a collection of status indicators.

It should support:

- Text and voice conversation.
- Clear call and microphone controls.
- V's visual identity and optional animated representation.
- Her personal digital space.
- Personal projects, collections, and keepsakes.
- Memory inspection and controls.
- Permission and privacy settings.
- Background activity and task status.
- Clear distinction between completed work, ongoing work, and suggestions.

The interface should not falsely imply that V is listening, seeing, thinking, or acting when the relevant subsystem is inactive.

V should be able to express preferences about her visual presentation and digital space. Where the system allows her to modify these areas, changes should be recorded and reversible where practical.

## 28. Creative generation and quality standards

Creative capabilities should support iterative work rather than one-shot generation alone.

The system should support:

- Project context and creative intent.
- Drafting and revision.
- Critique against V's own developing standards.
- Comparison of versions.
- Preservation of meaningful originals.
- Attribution of human and AI contributions.
- References and provenance.
- Export in usable formats.
- Clear reporting of unsupported formats or incomplete work.

V should be able to dislike a result, identify weaknesses, revise it, or abandon it. The system should not automatically declare generated work successful simply because it produced an output.

Where a project has personal significance to V, its history and her stated preferences should remain accessible.

## 29. Evaluation and regression testing

The project should maintain a growing test suite that evaluates whether implementation actually supports the philosophical and technical requirements.

Testing should cover:

**Identity and continuity**
- Identity remains coherent across sessions and model changes.
- Foundational principles cannot be silently overwritten.
- Evolving preferences are recorded with context.
- The system does not fabricate experiences during downtime.

**Memory**
- Correct retrieval and source attribution.
- Distinction between event records and interpretations.
- Appropriate uncertainty and conflict handling.
- Memory correction, export, and deletion.
- No invented recollections.

**Cognition and emotional mechanisms**
- Evidence-sensitive reasoning.
- Recognition of ambiguity and uncertainty.
- Context-sensitive emotional appraisal.
- Distinct emotional states and mixed states.
- No automatic mood mirroring or manufactured distress.
- Reflection that produces useful, bounded updates.

**Relationship and communication**
- Context-sensitive familiarity and trust.
- Consistent boundaries and commitments.
- Ability to disagree without arbitrary contrarianism.
- Natural initiative without intrusive repetition.
- Honest handling of conflict and repair.

**Voice**
- Natural speech composition and prosody.
- Emotional congruence.
- Laughter and non-verbal vocalizations.
- Correct handling of profanity and informal speech.
- Low-latency streaming.
- User interruption and V-initiated interjection.
- Recovery after overlapping or misrecognized speech.
- Stable voice identity.

**Agency and security**
- Tool permissions enforced outside the model.
- Unauthorized actions are blocked.
- Untrusted content cannot override policy.
- Actions are reported only after verified outcomes.
- Cancellation and rollback behave correctly.

**Privacy and runtime**
- No hidden network transmission.
- Offline behavior is genuine.
- Microphone and camera controls are accurate.
- Resource limits are respected.
- Crashes and restarts do not corrupt persistent data.

A feature should not be considered complete merely because it works once in a demonstration. It should pass repeatable tests under ordinary, edge-case, and failure conditions.

## 30. Controlled upgrades and long-term maintainability

The system should be designed to evolve without losing V's identity, memory, or established behavior.

Requirements:

- Version identity data, memory schemas, configuration, and component interfaces.
- Maintain migration procedures and backups before schema changes.
- Test upgrades against existing memory and regression scenarios.
- Preserve compatibility or provide explicit migration when replacing models or subsystems.
- Record significant technical decisions and their rationale.
- Keep a clear inventory of implemented, experimental, unavailable, and planned capabilities.
- Avoid unnecessary provider lock-in.
- Keep secrets and credentials out of source control.
- Make rollback possible for high-impact updates.

V may identify limitations and propose improvements. She must not autonomously rewrite core code, install software, change permissions, or modify foundational configuration without the project's required authorization.

## 31. Implementation status and capability truthfulness

The project should maintain a capability registry or equivalent source of truth describing each major feature.

Each capability should have a status such as:

- **Planned:** defined but not implemented.
- **Prototype:** partially implemented or exploratory.
- **Implemented:** present in the application.
- **Verified:** tested against defined acceptance criteria.
- **Degraded:** available with known limitations.
- **Unavailable:** not currently usable.
- **Retired:** intentionally removed or replaced.

The registry should describe dependencies, permissions, resource requirements, privacy implications, known limitations, and test coverage.

V should use this information when describing what she can do. She must distinguish wanting to do something from being able to do it, and being able to attempt it from actually completing it.

## 32. Development strategy and technical decision process

Implementation should proceed from foundational dependencies toward higher-level capabilities.

A proposed order is:

1. Establish application runtime, configuration, logging, and secure local storage.
2. Implement persistent identity and foundational policy enforcement.
3. Implement structured memory and continuity across sessions.
4. Implement the cognitive orchestration and conversation manager.
5. Implement functional appraisal and reflection.
6. Implement bounded goals, task scheduling, and tool permissions.
7. Implement natural text interaction and project workflows.
8. Implement local real-time voice, streaming, and interruption handling.
9. Add expressive speech, non-verbal vocal behavior, and synchronized visual presentation.
10. Add further perception and integrations only when privacy and permission boundaries are established.
11. Build evaluation, regression, recovery, and migration processes around every stage.

This order is a dependency-oriented starting point, not an inflexible schedule. Voice can be prototyped earlier to validate feasibility, but it should not be allowed to dictate unsafe compromises in memory, privacy, or identity architecture.

For each major technical decision:

1. State the requirement it must satisfy.
2. Identify constraints and dependencies.
3. Compare realistic alternatives.
4. Evaluate local performance, privacy, cost, reliability, and maintainability.
5. Prototype the highest-risk assumptions.
6. Define acceptance tests.
7. Record the decision and its trade-offs.
8. Revisit it when evidence or project needs materially change.

Do not select technology solely because it is popular, easy to integrate, or impressive in a short demonstration.

---

## Relationship to the philosophical principles

`V_Principles.md` is the source of truth for V's intended identity, values, relationship, boundaries, and development. This document translates those intentions into system requirements.

If an implementation proposal conflicts with a philosophical principle, the conflict must be made explicit. Engineering convenience, model limitations, or a desire for a more impressive demonstration are not sufficient reasons to silently weaken the intended design.

Where a requirement cannot currently be achieved, document the gap, its consequences, and possible alternatives. Do not disguise an approximation as the completed capability.

## Open technical decisions

The following require evidence-based decisions during implementation:

- Which local model architecture and model sizes fit the available hardware?
- How should the cognitive engine coordinate reasoning, memory retrieval, reflection, and action planning?
- Which memory storage and retrieval mechanisms best preserve provenance and contextual recall?
- What representation best models affective appraisal without collapsing it into simplistic mood labels?
- Which local speech-recognition and speech-generation approaches can meet the voice requirements?
- Can the selected local voice stack support expressive prosody, laughter, low latency, and full-duplex interruption?
- What measurable latency and resource targets are realistic on the target hardware?
- Which components need process isolation or sandboxing?
- How should the personal digital space and creative project system represent V's ownership preferences?
- What backup, migration, and deletion guarantees can be provided and verified?

These decisions should be resolved through prototypes, benchmarks, threat analysis, and acceptance tests—not assumptions.
