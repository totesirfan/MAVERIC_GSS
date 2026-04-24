"""TX command runner — parse → validate → encode → render → frame.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contract.commands import (
    CommandDraft,
    CommandRendering,
    EncodedCommand,
    FramedCommand,
    ValidationIssue,
)
from ..contract.mission import MissionSpec


@dataclass(frozen=True, slots=True)
class PreparedCommand:
    """Output of ``prepare_command`` — mission-validated command ready to queue.

    ``draft`` is the parsed mission input, ``encoded`` holds the inner
    bytes plus guard flag plus mission-opaque payload, and ``rendering``
    carries the UI row + detail blocks for queue display.
    """
    draft: CommandDraft
    encoded: EncodedCommand
    rendering: CommandRendering


class CommandRejected(ValueError):
    """Raised when mission validation rejects a command.

    Carries the list of ``ValidationIssue`` entries with ``severity="error"``;
    the message is their concatenated ``message`` fields so a plain
    ``str(exc)`` still surfaces the reason to the operator.
    """

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues) or "command rejected")


def prepare_command(mission: MissionSpec, value: str | dict[str, Any]) -> PreparedCommand:
    """Run the mission command capability before platform queue insertion.

    Bytes are only returned after parse, validate, encode, and render succeed.
    The platform queue/send layers should call this before persisting a command.
    """

    if mission.commands is None:
        raise CommandRejected([ValidationIssue("mission does not support commands")])

    draft = mission.commands.parse_input(value)
    issues = mission.commands.validate(draft)
    blocking = [i for i in issues if i.severity == "error"]
    if blocking:
        raise CommandRejected(blocking)

    encoded = mission.commands.encode(draft)
    rendering = mission.commands.render(encoded)
    return PreparedCommand(draft=draft, encoded=encoded, rendering=rendering)


def frame_command(mission: MissionSpec, encoded: EncodedCommand) -> FramedCommand:
    """Call the mission's framer. Raises CommandRejected if unsupported."""
    if mission.commands is None:
        raise CommandRejected([ValidationIssue("mission does not support commands")])
    return mission.commands.frame(encoded)
