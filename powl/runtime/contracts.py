from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Sequence, Union, Awaitable


class Standing(str, Enum):
    UNKNOWN = "UNKNOWN"
    PARTIAL_ALIVE = "PARTIAL_ALIVE"
    ALIVE = "ALIVE"
    BLOCKED = "BLOCKED"
    BUILD_BROKEN = "BUILD_BROKEN"
    UNSUPPORTED = "UNSUPPORTED"
    REFUSED = "REFUSED"


class StepKind(str, Enum):
    ACTIVITY = "activity"
    ACTIVITY_ATTEMPT = "activity_attempt"
    SILENT = "silent"
    SELECTION = "selection"
    DIAGNOSTIC = "diagnostic"


class RefusalCode(str, Enum):
    ADMISSION = "ADMISSION"
    AMBIGUOUS_SELECTION = "AMBIGUOUS_SELECTION"
    INVALID_SELECTION = "INVALID_SELECTION"
    RUN_ID_REUSE = "RUN_ID_REUSE"
    UNSTABLE_IDENTITY = "UNSTABLE_IDENTITY"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"
    UNRECEIPTED_ACTUATION = "UNRECEIPTED_ACTUATION"
    TIMEOUT = "TIMEOUT"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    CLAIM_CONFLICT = "CLAIM_CONFLICT"
    ABANDONED_CLAIM = "ABANDONED_CLAIM"
    CANCELLED = "CANCELLED"
    BOUND_EXCEEDED = "BOUND_EXCEEDED"


class SelectionRefused(Exception):
    def __init__(self, code: RefusalCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must be >= 0")

    def delay_for(self, attempt: int) -> float:
        if attempt < 1:
            return 0.0
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))


@dataclass(frozen=True)
class RunnerConfig:
    max_concurrency: int = 64
    activity_timeout_seconds: float = 300.0
    claim_lease_seconds: float = 360.0
    claim_poll_seconds: float = 0.05
    claim_wait_seconds: float = 30.0
    max_choice_steps: int = 10000
    max_repetitions: int = 10000
    max_model_nodes: int = 100000
    require_stable_ids: bool = True
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.activity_timeout_seconds <= 0:
            raise ValueError("activity_timeout_seconds must be > 0")
        if self.claim_lease_seconds <= self.activity_timeout_seconds:
            raise ValueError("claim_lease_seconds must be greater than activity_timeout_seconds")
        if self.claim_poll_seconds <= 0:
            raise ValueError("claim_poll_seconds must be > 0")
        if self.claim_wait_seconds < 0:
            raise ValueError("claim_wait_seconds must be >= 0")
        if self.max_choice_steps < 1:
            raise ValueError("max_choice_steps must be >= 1")
        if self.max_repetitions < 0:
            raise ValueError("max_repetitions must be >= 0")
        if self.max_model_nodes < 1:
            raise ValueError("max_model_nodes must be >= 1")


@dataclass(frozen=True)
class ActivityCommand:
    run_id: str
    workflow_id: str
    model_digest: str
    step_id: str
    idempotency_key: str
    attempt: int
    label: str
    organization: Optional[str]
    role: Optional[str]
    attributes: Mapping[str, Any]
    inputs: Mapping[str, Any]
    variables: Mapping[str, Any]


@dataclass(frozen=True)
class ActuationReceipt:
    receipt_id: str
    standing: Standing
    output: Any = None
    retryable: bool = False
    consequence_digest: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None


class ReceiptActuator(Protocol):
    def actuate(self, command: ActivityCommand) -> Union[ActuationReceipt, Awaitable[ActuationReceipt]]:
        ...


@dataclass(frozen=True)
class RepetitionDecision:
    key: str
    min_freq: int
    max_freq: Optional[int]
    model_type: str


@dataclass(frozen=True)
class ChoiceCandidate:
    execution_id: str
    model_type: str
    label: Optional[str]


@dataclass(frozen=True)
class ChoiceDecision:
    key: str
    candidates: Sequence[ChoiceCandidate]
    can_end: bool


class SelectionPolicy(Protocol):
    def repetitions(self, decision: RepetitionDecision) -> int:
        ...

    def choose(self, decision: ChoiceDecision) -> Optional[str]:
        ...


class StrictSelectionPolicy:
    """Refuse every business-semantic choice that is not structurally forced."""

    def repetitions(self, decision: RepetitionDecision) -> int:
        if decision.max_freq is not None and decision.min_freq == decision.max_freq:
            return decision.min_freq
        raise SelectionRefused(
            RefusalCode.AMBIGUOUS_SELECTION,
            "frequency requires an explicit selection for %s" % decision.key,
        )

    def choose(self, decision: ChoiceDecision) -> Optional[str]:
        if not decision.candidates and decision.can_end:
            return None
        if len(decision.candidates) == 1 and not decision.can_end:
            return decision.candidates[0].execution_id
        raise SelectionRefused(
            RefusalCode.AMBIGUOUS_SELECTION,
            "choice requires an explicit selection for %s" % decision.key,
        )


class TableSelectionPolicy:
    """Replayable decision table with strict fallback for unspecified choices."""

    def __init__(
        self,
        *,
        repetitions: Optional[Mapping[str, int]] = None,
        choices: Optional[Mapping[str, Optional[str]]] = None,
        fallback: Optional[SelectionPolicy] = None,
    ) -> None:
        self._repetitions = dict(repetitions or {})
        self._choices = dict(choices or {})
        self._fallback = fallback or StrictSelectionPolicy()

    def repetitions(self, decision: RepetitionDecision) -> int:
        if decision.key in self._repetitions:
            return self._repetitions[decision.key]
        return self._fallback.repetitions(decision)

    def choose(self, decision: ChoiceDecision) -> Optional[str]:
        if decision.key in self._choices:
            return self._choices[decision.key]
        return self._fallback.choose(decision)


@dataclass(frozen=True)
class StepReceipt:
    run_id: str
    workflow_id: str
    model_digest: str
    step_id: str
    kind: StepKind
    standing: Standing
    attempt: int
    started_at: float
    finished_at: float
    receipt_id: Optional[str] = None
    consequence_digest: Optional[str] = None
    reason: Optional[str] = None
    output: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReceipt:
    run_id: str
    workflow_id: str
    model_digest: str
    standing: Standing
    started_at: float
    finished_at: float
    receipt_digest: str
    steps: Sequence[StepReceipt]
    reason: Optional[str] = None
    replayed: bool = False


@dataclass(frozen=True)
class RunBinding:
    run_id: str
    workflow_id: str
    model_digest: str


class BindState(str, Enum):
    BOUND = "BOUND"
    EXISTING = "EXISTING"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class BindResult:
    state: BindState
    binding: RunBinding
    receipt: Optional[RunReceipt] = None


class ClaimState(str, Enum):
    ACQUIRED = "ACQUIRED"
    BUSY = "BUSY"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class ClaimResult:
    state: ClaimState
    receipt: Optional[StepReceipt] = None
