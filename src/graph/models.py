"""Pydantic models for all 11 node types in the KG schema v2."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── 1.1 Project ──
class ProjectNode(BaseModel):
    projectId: str
    name: str
    description: str | None = None
    file_path: str


# ── 1.2 File ──
class FileNode(BaseModel):
    name: str
    filePath: str
    modifiedAt: str | None = None


# ── 1.3 Function Component ──
class FunctionComponentNode(BaseModel):
    name: str
    filePath: str
    uid: str = ""
    syntax: str = "function"  # "function" | "arrow"
    usesHooks: bool = False
    returnsJSX: bool = True
    exportType: str = "none"  # "default" | "named" | "none"
    isRoot: bool = False

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.filePath}"
        return self.uid


# ── 1.4 Class Component ──
class ClassComponentNode(BaseModel):
    name: str
    filePath: str
    uid: str = ""
    extendsClass: str = "React.Component"
    returnsJSX: bool = True
    exportType: str = "none"
    isRoot: bool = False
    hasConstructor: bool = False
    lifecycleMethods: list[str] = Field(default_factory=list)

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.filePath}"
        return self.uid


# ── 1.5 Library Hook ──
class LibraryHookNode(BaseModel):
    name: str
    source: str
    uid: str = ""

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.source}"
        return self.uid


# ── 1.6 Custom Hook ──
class CustomHookNode(BaseModel):
    name: str
    filePath: str
    uid: str = ""
    exportType: str = "none"

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.filePath}"
        return self.uid


# ── 1.7 Prop ──
class PropNode(BaseModel):
    name: str
    filePath: str
    componentName: str
    uid: str = ""
    type: str = "unknown"
    isRequired: bool | None = None

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.componentName}::{self.filePath}"
        return self.uid


# ── 1.8 State Variable ──
class StateVariableNode(BaseModel):
    name: str
    setterName: str
    filePath: str
    componentName: str
    uid: str = ""
    type: str = "unknown"
    defaultValue: str | None = None

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.componentName}::{self.filePath}"
        return self.uid


# ── 1.9 Context ──
class ContextNode(BaseModel):
    name: str
    filePath: str
    uid: str = ""
    defaultValue: str | None = None
    exportType: str = "none"

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.filePath}"
        return self.uid


# ── 1.10 EventHandler ──
class EventHandlerNode(BaseModel):
    name: str
    eventType: str
    filePath: str
    componentName: str
    uid: str = ""
    isInline: bool = False

    def compute_uid(self) -> str:
        self.uid = f"{self.name}::{self.componentName}::{self.filePath}"
        return self.uid


# ── 1.11 Library ──
class LibraryNode(BaseModel):
    name: str
    version: str | None = None
    category: str | None = None


# ── LLM Response Models (for Instructor validation) ──

class HookDetail(BaseModel):
    name: str
    category: str  # "library" | "custom"
    source: str


class FunctionComponentExtraction(BaseModel):
    name: str
    syntax: str
    usesHooks: bool
    hookDetails: list[HookDetail] = Field(default_factory=list)
    returnsJSX: bool
    exportType: str


class FunctionComponentResponse(BaseModel):
    components: list[FunctionComponentExtraction] = Field(default_factory=list)


class CustomHookExtraction(BaseModel):
    """One custom hook *definition* found in a file.

    Populated by the `custom_hook` prompt. Hook definitions were previously only a
    by-product of component extraction, which never fired for hook files — a hook
    returns an object, not JSX, so `function_component.jinja2` correctly declined
    them and `Custom_Hook` nodes were absent from every extracted project.
    """
    name: str
    syntax: str = "function"  # "function" | "arrow"
    exportType: str = "none"  # "default" | "named" | "none"
    parameters: list[str] = Field(default_factory=list)
    returnShape: str = "unknown"


class CustomHookResponse(BaseModel):
    customHooks: list[CustomHookExtraction] = Field(default_factory=list)


class ClassComponentExtraction(BaseModel):
    name: str
    extendsClass: str
    from_field: str = Field(alias="from", default="react")
    exportType: str
    hasConstructor: bool
    lifecycleMethods: list[str] = Field(default_factory=list)
    returnsJSX: bool


class ClassComponentResponse(BaseModel):
    classComponents: list[ClassComponentExtraction] = Field(default_factory=list)


class PropExtraction(BaseModel):
    name: str
    componentName: str
    type: str = "unknown"
    isRequired: bool | None = None


class EventHandlerExtraction(BaseModel):
    name: str
    eventType: str
    componentName: str
    isInline: bool = False


class PropAndHandlerResponse(BaseModel):
    props: list[PropExtraction] = Field(default_factory=list)
    eventHandlers: list[EventHandlerExtraction] = Field(default_factory=list)


class LibraryImportExtraction(BaseModel):
    from_field: str = Field(alias="from")
    symbols: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)


class LibraryUsageResponse(BaseModel):
    imports: list[LibraryImportExtraction] = Field(default_factory=list)


class StateVariableExtraction(BaseModel):
    name: str
    setterName: str
    type: str = "unknown"
    defaultValue: str = "undefined"
    componentName: str
    declarationPattern: str = "useState"


class FunctionStateResponse(BaseModel):
    stateVariables: list[StateVariableExtraction] = Field(default_factory=list)


class ClassStateVariableExtraction(BaseModel):
    name: str
    setterName: str = "this.setState"
    type: str = "unknown"
    defaultValue: str = "undefined"
    componentName: str
    declarationStyle: str = "constructor"


class ClassStateResponse(BaseModel):
    classStateVariables: list[ClassStateVariableExtraction] = Field(default_factory=list)


class ContextExtraction(BaseModel):
    name: str
    defaultValue: str = "undefined"
    exportType: str = "none"


class ContextResponse(BaseModel):
    contexts: list[ContextExtraction] = Field(default_factory=list)


# ── Stage 4 Cross-File LLM Response Models ──

class PropPassed(BaseModel):
    propName: str
    valueExpression: str = ""


class ComponentUsageExtraction(BaseModel):
    parentComponent: str
    childComponent: str
    importSource: str
    usage: str = "element"
    propsPassed: list[PropPassed] = Field(default_factory=list)


class CompositionResponse(BaseModel):
    componentUsages: list[ComponentUsageExtraction] = Field(default_factory=list)


class LibraryHookUsage(BaseModel):
    name: str
    source: str
    count: int = 1


class CustomHookUsage(BaseModel):
    name: str
    source: str


class CustomHookInternalUsage(BaseModel):
    hookName: str
    libraryHooks: list[LibraryHookUsage] = Field(default_factory=list)
    customHooks: list[CustomHookUsage] = Field(default_factory=list)


class CustomHookInternalResponse(BaseModel):
    customHookUsages: list[CustomHookInternalUsage] = Field(default_factory=list)


class ContextProviderExtraction(BaseModel):
    componentName: str
    contextName: str
    contextSource: str
    valueExpression: str = ""


class ContextConsumerExtraction(BaseModel):
    consumerName: str
    consumerType: str  # "function_component" | "class_component" | "custom_hook"
    contextName: str
    contextSource: str
    consumptionMethod: str = "useContext"


class ContextProviderConsumerResponse(BaseModel):
    contextProviders: list[ContextProviderExtraction] = Field(default_factory=list)
    contextConsumers: list[ContextConsumerExtraction] = Field(default_factory=list)


class RouteDefinitionExtraction(BaseModel):
    routingComponent: str
    targetComponent: str
    importSource: str
    path: str
    isNested: bool = False
    isLazy: bool = False
    isProtected: bool = False


class RouteDefinitionResponse(BaseModel):
    routeDefinitions: list[RouteDefinitionExtraction] = Field(default_factory=list)
