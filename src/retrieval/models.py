"""Data models for retrieval results and round history."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, computed_field


class RoundRecord(BaseModel):
    """Record of a single retrieval round."""

    round_number: int
    query: str
    retrieved_files: list[str]
    context_snippet: str
    token_count: int


class RetrievalResult(BaseModel):
    """Complete result from a retrieval operation."""

    context: str
    rounds: list[RoundRecord]
    retriever_name: str
    condition_id: str
    total_token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComponentContext(BaseModel):
    """Context for a single component surfaced by retrieval."""

    name: str
    file_path: str
    source_code: str | None = None
    component_type: str
    # How this component relates to the anchor ("parent", "child", "caller",
    # "used_by"). Empty for anchors themselves. Without it a hook's consumers
    # render indistinguishably from a component's prop-passing parents.
    relation: str = ""
    props: list[dict[str, Any]] = Field(default_factory=list)
    hooks: list[dict[str, Any]] = Field(default_factory=list)
    state_variables: list[dict[str, Any]] = Field(default_factory=list)
    contexts_consumed: list[str] = Field(default_factory=list)
    contexts_provided: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def required_props(self) -> list[str]:
        """Names of props the component requires.

        Rendered separately from the prop list because required-ness is the part
        that breaks the build: P2's kg_augmented candidates rendered a component
        whose `dataTestID` prop is mandatory and omitted it, failing on
        `TS2741: Property 'dataTestID' is missing`. "There is a dataTestID prop"
        and "dataTestID is required" are different instructions.

        A computed_field rather than a plain property so it survives
        `model_dump()`, which is how the renderer passes data to the template.
        """
        return [p["name"] for p in self.props if p.get("isRequired") and p.get("name")]


class ContextData(BaseModel):
    """Structured data passed to format templates for rendering.

    Same data goes to every format variant — the template decides what to use.
    """

    task_spec: str
    task_type: str
    target_components: list[ComponentContext]
    neighbor_components: list[ComponentContext] = Field(default_factory=list)
    cross_cutting_notes: list[str] = Field(default_factory=list)
    project_name: str = ""
    retriever_name: str = ""
