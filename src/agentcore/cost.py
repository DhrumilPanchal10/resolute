from dataclasses import dataclass, field


@dataclass
class CallCost:
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


@dataclass
class RunCost:
    calls: list[CallCost] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def total_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    def record(self, call: CallCost) -> None:
        self.calls.append(call)
