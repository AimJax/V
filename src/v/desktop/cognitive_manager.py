"""Inspect functional cognitive state and manage goals and preferences."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from v.cognition import CognitiveStore


class CognitiveManagerDialog(QDialog):
    """User-facing state inspection and explicit goal/preference controls."""

    def __init__(self, store: CognitiveStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("V — Cognitive state")
        self.resize(700, 680)
        self.setMinimumSize(540, 500)

        layout = QVBoxLayout(self)
        heading = QLabel("Functional cognitive state")
        heading.setStyleSheet("font-size: 16pt; font-weight: 650;")
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            "These are local computational signals, not proof of subjective feelings."
        ))
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)

        layout.addWidget(QLabel("Goals"))
        self.goals = QListWidget()
        layout.addWidget(self.goals, 1)
        goal_controls = QHBoxLayout()
        add_goal = QPushButton("Add goal")
        add_goal.clicked.connect(self._add_goal)
        goal_controls.addWidget(add_goal)
        self.status_choice = QComboBox()
        for value, label in (
            ("active", "Active"), ("deferred", "Deferred"),
            ("completed", "Completed"), ("abandoned", "Abandoned"),
        ):
            self.status_choice.addItem(label, value)
        goal_controls.addWidget(self.status_choice)
        update_goal = QPushButton("Update selected")
        update_goal.clicked.connect(self._update_goal)
        goal_controls.addWidget(update_goal)
        layout.addLayout(goal_controls)

        layout.addWidget(QLabel("Pending evidence-backed goal candidates"))
        self.goal_proposals = QListWidget()
        layout.addWidget(self.goal_proposals, 1)
        candidate_controls = QHBoxLayout()
        propose_goal = QPushButton("Propose goal")
        propose_goal.clicked.connect(self._propose_goal)
        candidate_controls.addWidget(propose_goal)
        accept_goal = QPushButton("Accept candidate")
        accept_goal.clicked.connect(lambda: self._review_goal_proposal(True))
        candidate_controls.addWidget(accept_goal)
        reject_goal = QPushButton("Reject candidate")
        reject_goal.clicked.connect(lambda: self._review_goal_proposal(False))
        candidate_controls.addWidget(reject_goal)
        layout.addLayout(candidate_controls)

        layout.addWidget(QLabel("Pending evidence-backed preferences"))
        self.preferences = QListWidget()
        layout.addWidget(self.preferences, 1)
        preference_controls = QHBoxLayout()
        propose = QPushButton("Propose preference")
        propose.clicked.connect(self._propose_preference)
        preference_controls.addWidget(propose)
        accept = QPushButton("Accept")
        accept.clicked.connect(lambda: self._review_preference(True))
        preference_controls.addWidget(accept)
        reject = QPushButton("Reject")
        reject.clicked.connect(lambda: self._review_preference(False))
        preference_controls.addWidget(reject)
        layout.addLayout(preference_controls)

        footer = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        footer.addWidget(refresh)
        footer.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.refresh()

    def refresh(self) -> None:
        state = self.store.get_state()
        self.state_label.setText(
            f"Valence: {state.valence:.2f}   Activation: {state.activation:.2f}\n"
            f"Frustration: {state.frustration:.2f}   Curiosity: {state.curiosity:.2f}\n"
            f"Confidence: {state.confidence:.2f}\n"
            f"Last update: {state.updated_at}\n\n"
            "Signals decay over time. They may influence response attention and "
            "tone, but cannot grant permissions or trigger external actions."
        )
        self.goals.clear()
        for goal in self.store.list_goals(status="all"):
            row = QListWidgetItem(
                f"[{goal.status}] {goal.title} — {goal.origin} ({goal.priority:.2f})"
            )
            row.setData(256, goal.id)
            self.goals.addItem(row)
        self.goal_proposals.clear()
        for proposal in self.store.list_goal_proposals(status="pending"):
            row = QListWidgetItem(
                f"{proposal['title']} (priority {proposal['priority']:.2f})"
            )
            row.setData(256, proposal["id"])
            row.setToolTip(proposal["rationale"])
            self.goal_proposals.addItem(row)
        self.preferences.clear()
        for preference in self.store.list_preferences(status="pending"):
            row = QListWidgetItem(
                f"{preference['statement']} (confidence {preference['confidence']:.2f})"
            )
            row.setData(256, preference["id"])
            row.setToolTip(preference["rationale"])
            self.preferences.addItem(row)

    def _add_goal(self) -> None:
        title, accepted = QInputDialog.getText(self, "Add goal", "Goal title:")
        if not accepted or not title.strip():
            return
        try:
            self.store.create_goal(
                title, origin="user_requested",
                rationale="Explicitly created by the user in Cognitive Manager.",
            )
        except ValueError as error:
            self.state_label.setText(str(error))
            return
        self.refresh()

    def _update_goal(self) -> None:
        item = self.goals.currentItem()
        if item is None:
            return
        try:
            self.store.update_goal(
                str(item.data(256)),
                str(self.status_choice.currentData()),
                rationale="Status changed explicitly by the user.",
            )
        except (KeyError, ValueError) as error:
            self.state_label.setText(str(error))
            return
        self.refresh()

    def _propose_goal(self) -> None:
        title, accepted = QInputDialog.getText(
            self, "Propose goal", "Candidate goal title:"
        )
        if not accepted or not title.strip():
            return
        evidence, accepted = QInputDialog.getText(
            self, "Goal evidence", "Evidence references (comma-separated):"
        )
        if not accepted:
            return
        refs = tuple(part.strip() for part in evidence.split(",") if part.strip())
        priority, accepted = QInputDialog.getDouble(
            self, "Goal priority", "Priority:", 0.5, 0.0, 1.0, 2
        )
        if not accepted:
            return
        try:
            self.store.propose_goal(
                title, evidence_refs=refs, priority=priority,
                rationale="Submitted as a candidate for explicit user review.",
            )
        except ValueError as error:
            self.state_label.setText(str(error))
            return
        self.refresh()

    def _review_goal_proposal(self, accept: bool) -> None:
        item = self.goal_proposals.currentItem()
        if item is None:
            return
        try:
            self.store.review_goal_proposal(str(item.data(256)), accept=accept)
        except (KeyError, ValueError) as error:
            self.state_label.setText(str(error))
            return
        self.refresh()

    def _propose_preference(self) -> None:
        statement, accepted = QInputDialog.getText(
            self, "Propose preference", "Preference statement:"
        )
        if not accepted or not statement.strip():
            return
        evidence, accepted = QInputDialog.getText(
            self, "Preference evidence", "Evidence references (comma-separated):"
        )
        if not accepted:
            return
        refs = tuple(part.strip() for part in evidence.split(",") if part.strip())
        confidence, accepted = QInputDialog.getDouble(
            self, "Preference confidence", "Confidence:", 0.7, 0.0, 1.0, 2
        )
        if not accepted:
            return
        try:
            self.store.propose_preference(
                statement, evidence_refs=refs, confidence=confidence,
                rationale="Submitted for explicit user review in Cognitive Manager.",
            )
        except ValueError as error:
            self.state_label.setText(str(error))
            return
        self.refresh()

    def _review_preference(self, accept: bool) -> None:
        item = self.preferences.currentItem()
        if item is None:
            return
        try:
            self.store.review_preference(str(item.data(256)), accept=accept)
        except KeyError as error:
            self.state_label.setText(str(error))
            return
        self.refresh()
