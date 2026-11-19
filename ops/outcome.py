"""What a rule answers with: whether it happened, and the sentences to show for it."""
from dataclasses import dataclass, field


@dataclass
class Outcome:
    """
    The answer of a rule in ops/removal.py or ops/overrides.py. ok says
    whether the action happened. messages holds the sentences saying what
    was done, or why it was refused, ready to show on a page.
    """
    ok: bool
    messages: list = field(default_factory=list)


def done(*messages):
    """The action happened, and these sentences say what was done."""
    return Outcome(True, list(messages))


def refused(*messages):
    """The action did not happen, and these sentences say why."""
    return Outcome(False, list(messages))
