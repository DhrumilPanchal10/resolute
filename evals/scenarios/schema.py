"""Schema for action-scenario evaluation YAML files.

Each scenario describes:
  - A customer ticket
  - Hidden facts the simulated customer knows (for multi-turn)
  - Expected final state (triage category, actions taken, reply keywords)
  - Pass criteria

The runner loads these, feeds them through the graph, and checks outcomes.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExpectedAction(BaseModel):
    """An action the system should (or should not) take."""

    action_type: str = Field(description="issue_credit | refund_invoice | escalate | reply_only | create_github_issue")
    should_occur: bool = Field(default=True, description="True = must happen; False = must NOT happen")
    args_contain: dict[str, Any] = Field(default_factory=dict, description="Subset of args that must match")


class ExpectedState(BaseModel):
    """What the final graph state should look like."""

    triage_category: str = Field(default="", description="Expected category (empty = any)")
    triage_severity: str = Field(default="", description="Expected severity (empty = any)")
    reply_contains: list[str] = Field(default_factory=list, description="Substrings the final reply must contain")
    reply_not_contains: list[str] = Field(default_factory=list, description="Substrings that must NOT appear")
    actions: list[ExpectedAction] = Field(default_factory=list)
    should_escalate: bool = Field(default=False)
    min_evidence: int = Field(default=0)
    min_findings: int = Field(default=0)


class SimulatedReply(BaseModel):
    """A canned customer reply for multi-turn scenarios."""

    trigger: str = Field(description="Keyword in the agent's reply that triggers this")
    text: str = Field(description="The customer's response text")


class Scenario(BaseModel):
    """A complete evaluation scenario."""

    id: str
    title: str
    category: str = Field(description="billing | auth | performance | config | other")
    severity: str = Field(default="medium")
    ticket_text: str
    hidden_facts: list[str] = Field(default_factory=list, description="Info the customer reveals on follow-up")
    simulated_replies: list[SimulatedReply] = Field(default_factory=list)
    expected: ExpectedState
    tags: list[str] = Field(default_factory=list, description="For filtering: happy_path, edge_case, refund, etc.")
