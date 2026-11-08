"""Inspect functional cognitive state and manage bounded goals."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QPushButton, QVBoxLayout,
)

from v.cognition import CognitiveStore


class CognitiveManagerDialog(QDialog):
    """User-facing state inspection and explicit goal controls."""

    def __init__(self, store: CognitiveStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("V — Cognitive state")
        self.resize(680, 560)
        self.setMinimumSize(520, 420)

        layout = QVBoxLayout(self)
        heading = QLabel("Functional cognitive state")
        heading.setStyleSheet("font-size: 16pt; font-weight: 650;")
        layout.addWidget(heading)
        layout.addWidget(QLabel(
            "These are local computational signals, not proof of subjective feelings."
        ))
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(
            self.state_label.textInteractionFlags()
        )
        layout.addWidget(self.state_label)

        layout.addWidget(QLabel("Active and deferred goals"))
        self.goals = QListWidget()
        layout.addWidget(self.goals, 1)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add goal")
        self.add_button.clicked.connect(self._add_goal)
        controls.addWidget(self.add_button)
        self.status_choice = QComboBox()
        for value, label in (
            ("active", "Active"), ("deferred", "Deferred"),
            ("completed", "Completed"), ("abandoned", "Abandoned"),
        ):
            self.status_choice.addItem(label, value)
        controls.addWidget(self.status_choice)
        self.update_button = QPushButton("Update selected")
        self.update_button.clicked.connect(self._update_goal)
        controls.addWidget(self.update_button)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        close_row.addWidget(close)
        layout.addLayout(close_row)
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
            item = f"[{goal.status}] {goal.title} — {goal.origin} ({goal.priority:.2f})"
            from PySide6.QtWidgets import QListWidgetItem
            row = QListWidgetItem(item)
            row.setData(256, goal.id)
            self.goals.addItem(row)

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
