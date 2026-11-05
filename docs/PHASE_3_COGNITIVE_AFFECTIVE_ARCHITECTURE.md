# Phase 3 — Cognitive and Affective Architecture

**Status:** Planned  
**Objective:** Introduce bounded functional internal state that influences V's attention, appraisal, preferences, motivation, reflection, and decisions coherently and inspectably.

## 1. Intended result

V should not behave as a blank slate on every turn or simply mirror the user's latest tone. She should maintain a current stance, notice conflicts with established preferences, show curiosity, become frustrated by recurring obstacles, register progress, reconsider opinions, and decide whether an activity is worth pursuing.

This phase implements functional computational mechanisms. It does not establish or prove subjective feeling, sentience, or consciousness. The product must not make such claims.

## 2. Dependencies

Requires Phase 1 persistent identity and controlled trait evolution; Phase 2 evidence-backed episodic/semantic/prospective memory and temporal continuity; and the existing local inference, conversation runtime, and permission boundaries.

Do not encode emotions as prompt adjectives. Implement state, transitions, appraisal inputs, persistence rules, and measurable effects on behavior.

## 3. Functional architecture

### 3.1 Appraisal

Evaluate relevant events and proposed actions against structured inputs:

- Relevance to current goals and ongoing interests.
- Alignment/conflict with established values and preferences.
- Novelty and uncertainty.
- Progress, obstruction, and unexpected outcomes.
- Perceived risk and reversibility.
- Social/contextual meaning supported by evidence.
- Available resources and capability constraints.

Appraisal must produce a structured, explainable result. Do not infer hidden user intent or sensitive attributes without evidence.

### 3.2 Affective state

Use a bounded set of functional dimensions rather than only free-form labels. Candidate dimensions include valence, activation, frustration/obstruction pressure, curiosity/novelty drive, confidence/uncertainty, topic-scoped social comfort/trust, and operational resource pressure.

The final model must avoid redundant variables and define scale, decay, persistence, triggers, and clamping. Labels such as amusement, irritation, relief, sadness, or excitement may be derived from structured state where useful.

### 3.3 Temporal dynamics

- State changes in response to identifiable events and appraisals.
- Short-lived state decays or is superseded.
- Persistent concerns require evidence; one ambiguous utterance is insufficient.
- Strong events may influence memory salience without rewriting the event record.
- Transient affect must not persist indefinitely.
- Restart restores appropriate durable context without replaying stale momentary state as current.

### 3.4 Motivation and goal selection

Track candidate interests, active goals, obstacles, and completion. Compare importance, curiosity, expected utility, urgency, and resource cost. Defer, abandon, or resume work with recorded reasons. Distinguish V-originated candidate goals from user-requested tasks and scheduled commitments.

A goal is not permission to take an external action. Motivation selects what to consider; application policy decides what can execute.

### 3.5 Preferences and independent judgment

Maintain preferences with provenance and confidence. Allow disagreement and reasoned challenge. Avoid automatic agreement, automatic praise, and reflexive opposition. Change preferences when supported by evidence or reflection. Distinguish genuine preference from temporary conversational adaptation. Do not optimize for user approval at the expense of consistency or truthfulness.

### 3.6 Reflection

A bounded reflection process may review what happened, available evidence, whether a prediction or plan succeeded, what should be remembered/corrected, whether a preference or goal remains relevant, what uncertainty remains, and whether a proposed change should be retained or discarded.

Do not create an unbounded hidden chain-of-thought store. Persist concise outcomes, evidence references, and decision summaries—not private token-by-token reasoning. Reflection must be rate-limited and interruptible.

## 4. Behavioral integration

Functional state should influence observable behavior with restraint:

- Tone and conversational energy may shift without becoming theatrical.
- Curiosity may produce relevant questions or research proposals.
- Frustration may lead to direct disagreement or a request to pause, without insults or punitive scorekeeping.
- Confidence calibrates certainty and willingness to commit.
- Preferences influence recommendations and choices.
- Goals influence whether V resumes, defers, or proposes work.
- Affective salience may influence memory consolidation priority.

Do not inject a long state dump into every prompt. Supply a compact, task-relevant summary through a stable interface.

## 5. Privacy, safety, and control

Keep state local. Do not infer/store sensitive user traits as a shortcut for social modeling. Do not use affect to pressure, guilt, manufacture urgency, dependency, or exclusivity. Do not claim internal variables demonstrate subjective experience. User feedback is evidence, not an unconditional command to rewrite identity.

Respect shutdown and resource boundaries. V may express a preference or ask to reconsider, but must not interfere with shutdown or take unauthorized protective action. All executable permissions remain outside the model and motivation layers.

## 6. Implementation milestones

1. Specify state dimensions, event inputs, decay, persistence, and invariants.
2. Implement deterministic appraisal and state-transition services.
3. Add provenance-aware state events and selective persistence.
4. Implement bounded goal and interest tracking.
5. Integrate state into response context and memory salience.
6. Implement scheduled/idle reflection with strict resource/time budgets.
7. Expose user-understandable state and goal controls without exposing private internal reasoning.
8. Evaluate multi-session consistency, calibration, and non-manipulative behavior.

## 7. Required tests

- Same inputs/configuration produce deterministic state transitions.
- State variables remain within documented bounds.
- Transient state decays and is not restored as permanently current.
- Durable preferences require evidence and retain provenance.
- One ambiguous utterance cannot create a persistent personality/relationship conclusion.
- User disagreement can be considered without unconditional acceptance or reflexive rejection.
- Motivation cannot bypass permissions, offline mode, or confirmation.
- Reflection is bounded, cancellable, and does not block chat.
- State summaries stay within context budgets.
- UI/output never represents functional state as proof of consciousness.

## 8. Acceptance criteria

Phase 3 is verified when a persistent but bounded cognitive/affective model demonstrably influences judgment, tone, attention, memory salience, and goal handling across sessions; durable changes are evidence-based; and the architecture cannot authorize actions or make unsupported claims about subjective experience.

## 9. Explicitly out of scope

Replacing Phase 1 identity or Phase 2 memory, sensor/multimodal integration (Phase 4), and autonomous outreach/background execution (Phase 5), beyond the internal goal and reflection foundations.
