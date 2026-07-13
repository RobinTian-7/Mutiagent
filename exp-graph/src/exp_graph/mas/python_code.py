"""Restricted validation contract for model-generated Python MAS programs.

The Python planner is intentionally independent from both free GraphGen and the
restricted phase DSL.  It accepts real Python, but only a small statically
auditable subset whose sole external effect is calling the existing
``LLMClient.complete`` API and writing one JSON object to stdout.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PYTHON_EXECUTION_CONTRACT_VERSION = "python_mas_v1"
PYTHON_AST_POLICY_VERSION = "python_ast_v1"

# 中文：Worker 输出合约。action_json_v1=旧模式(Worker 返回完整动作 JSON)；
#   message_only_v1=Planner source 决定路由/控制、Runtime 维护状态与 provenance、
#   Worker 只产出纯文本消息或最终答案；message_only_v2 在完整通信后统一提交，答案
#   必须是单一 JSON 值。三种合约的 scaffold、校验头、SkillBank 检索互相隔离；
#   缺省保持 action_json_v1 与历史行为逐字节一致。
# Worker output contracts. action_json_v1 = legacy mode (the worker returns a
# full action JSON). message_only_v1 = the planner source decides routing and
# control, the runtime owns state/provenance, and the worker only produces
# plain text. message_only_v2 adds a synchronized submit barrier and parses one
# canonical JSON answer value. Contract surfaces are isolated; the default
# keeps action_json_v1 byte-identical to historical behaviour.
PythonWorkerContract = Literal[
    "action_json_v1",
    "message_only_v1",
    "message_only_v2",
]
PYTHON_WORKER_CONTRACTS: tuple[str, ...] = (
    "action_json_v1",
    "message_only_v1",
    "message_only_v2",
)
DEFAULT_PYTHON_WORKER_CONTRACT = "action_json_v1"

PythonErrorType = Literal[
    "SyntaxError",
    "PolicyError",
    "APIError",
    "DataFlowError",
    "BudgetError",
    "OutputSchemaError",
    "AnswerFormatError",
    "RuntimeError",
]


class PythonCodeError(RuntimeError):
    """One sanitized validation or execution failure."""

    def __init__(
        self,
        error_type: PythonErrorType,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.line = line
        self.column = column

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


class PythonValidationReport(BaseModel):
    """Auditable result of the fail-closed static validation pipeline."""

    ast_policy_version: str = PYTHON_AST_POLICY_VERSION
    syntax_valid: bool = False
    policy_valid: bool = False
    api_valid: bool = False
    data_flow_valid: bool = False
    compile_valid: bool = False
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return bool(
            self.syntax_valid
            and self.policy_valid
            and self.api_valid
            and self.data_flow_valid
            and self.compile_valid
            and not self.errors
        )


class PythonSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: int
    answer: Any = None
    submitted_round: int | None = None


class PythonMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_sent: int = Field(ge=0)
    round_delivered: int = Field(ge=1)
    src: int
    dst: int
    source_ids: list[int] = Field(default_factory=list)
    body: Any = None

    @model_validator(mode="after")
    def validate_delivery_delay(self) -> "PythonMessage":
        if self.round_delivered != self.round_sent + 1:
            raise ValueError("messages must be delivered exactly one round later")
        if self.src == self.dst:
            raise ValueError("self-messages are not allowed")
        return self


class PythonUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class PythonProgramOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissions: list[PythonSubmission]
    rounds_executed: int = Field(ge=0)
    messages: list[PythonMessage] = Field(default_factory=list)
    usage: PythonUsage
    errors: list[dict[str, Any] | str] = Field(default_factory=list)


class PythonExecutionBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_model_calls: int = Field(ge=1)
    max_completion_tokens: int = Field(ge=1)
    max_messages: int = Field(ge=0)


class PythonWorkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0


class PythonAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: int = Field(ge=0)
    local_prompt: str | None = Field(default=None, min_length=1)
    communication_prompt: str | None = Field(default=None, min_length=1)
    submit_prompt: str | None = Field(default=None, min_length=1)


class PythonExecutionPayload(BaseModel):
    """The only host-to-program data shape; unknown/private fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    execution_contract_version: Literal["python_mas_v1"]
    # Contract selector for scaffold/validation/wrapper semantics. The default
    # keeps every pre-existing payload dict (which lacks the key) valid and
    # byte-identical in behaviour to the historical action-JSON mode.
    worker_contract: PythonWorkerContract = "action_json_v1"
    task_description: str
    information_goal: Literal["sink", "all_agents"]
    selected_primary: int = Field(ge=0)
    n_agents: int = Field(ge=1)
    max_rounds: int = Field(ge=1)
    budgets: PythonExecutionBudgets
    worker_llm: PythonWorkerConfig
    agents: list[PythonAgentInput]

    @model_validator(mode="after")
    def validate_agents(self) -> "PythonExecutionPayload":
        ids = [item.agent_id for item in self.agents]
        if ids != list(range(self.n_agents)):
            raise ValueError("agents must be ordered exactly by agent_id")
        if not 0 <= self.selected_primary < self.n_agents:
            raise ValueError("selected_primary is outside the agent range")
        if self.worker_contract == "message_only_v2":
            if any(item.local_prompt is not None for item in self.agents):
                raise ValueError(
                    "message_only_v2 agents must not carry the legacy local_prompt"
                )
            if any(
                item.communication_prompt is None or item.submit_prompt is None
                for item in self.agents
            ):
                raise ValueError(
                    "message_only_v2 agents require separate communication_prompt "
                    "and submit_prompt values"
                )
        else:
            if any(item.local_prompt is None for item in self.agents):
                raise ValueError(
                    f"{self.worker_contract} agents require local_prompt"
                )
            if any(
                item.communication_prompt is not None or item.submit_prompt is not None
                for item in self.agents
            ):
                raise ValueError(
                    f"{self.worker_contract} agents may not carry v2 split prompts"
                )
        return self


def python_source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


_ALLOWED_IMPORTS = {"json", "sys"}
_FORBIDDEN_NAMES = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "breakpoint",
    "input",
    "help",
    "print",
    "dir",
    "type",
    "object",
    "super",
    "property",
    "classmethod",
    "staticmethod",
    "exit",
    "quit",
}
_FORBIDDEN_MODULE_PREFIXES = {
    "os",
    "pathlib",
    "subprocess",
    "socket",
    "threading",
    "multiprocessing",
    "asyncio",
    "requests",
    "urllib",
    "http",
    "inspect",
    "importlib",
    "resource",
    "shutil",
    "tempfile",
    "builtins",
}
_FORBIDDEN_ATTRIBUTE_NAMES = {
    "system",
    "popen",
    "fork",
    "spawn",
    "connect",
    "sendall",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "unlink",
    "remove",
    "rmdir",
    "walk",
    "listdir",
    "environ",
    "argv",
    "modules",
    "path",
    "meta_path",
    "path_hooks",
}
_TAINT_TRANSFORMS = {
    "split",
    "rsplit",
    "partition",
    "rpartition",
    "replace",
    "strip",
    "lstrip",
    "rstrip",
    "encode",
    "format",
    "join",
}


def validate_python_source(
    source: str,
    *,
    worker_contract: str = DEFAULT_PYTHON_WORKER_CONTRACT,
) -> PythonValidationReport:
    """Validate source without executing it; every uncertainty fails closed.

    ``worker_contract`` selects which canonical worker-prompt headers the
    data-flow validator demands. The default keeps the historical
    action_json_v1 checks byte-identical; an unknown contract fails closed.
    """
    report = PythonValidationReport()
    if worker_contract not in PYTHON_WORKER_CONTRACTS:
        report.errors.append(
            PythonCodeError(
                "PolicyError",
                f"unknown python worker contract {worker_contract!r}",
            ).as_dict()
        )
        return report
    if any(marker in source.lower() for marker in ("todo", "notimplemented")):
        report.errors.append(
            PythonCodeError(
                "PolicyError",
                "program contains a TODO or unimplemented placeholder",
            ).as_dict()
        )
        return report
    try:
        tree = ast.parse(source, filename="program.py", mode="exec")
        report.syntax_valid = True
    except SyntaxError as exc:
        report.errors.append(
            PythonCodeError(
                "SyntaxError",
                exc.msg,
                line=exc.lineno,
                column=exc.offset,
            ).as_dict()
        )
        return report

    policy_errors = _PolicyValidator().validate(tree)
    if policy_errors:
        report.errors.extend(error.as_dict() for error in policy_errors)
        return report
    report.policy_valid = True

    api_errors = _APIValidator().validate(tree)
    if api_errors:
        report.errors.extend(error.as_dict() for error in api_errors)
        return report
    report.api_valid = True

    flow_errors = _DataFlowValidator(worker_contract=worker_contract).validate(tree)
    if flow_errors:
        report.errors.extend(error.as_dict() for error in flow_errors)
        return report
    report.data_flow_valid = True

    try:
        compile(tree, "program.py", "exec")
        report.compile_valid = True
    except Exception as exc:  # pragma: no cover - ast.parse normally guarantees it
        report.errors.append(PythonCodeError("SyntaxError", str(exc)).as_dict())
    return report


class _ValidationVisitor(ast.NodeVisitor):
    error_type: PythonErrorType = "PolicyError"

    def __init__(self) -> None:
        self.errors: list[PythonCodeError] = []

    def fail(self, node: ast.AST, message: str) -> None:
        self.errors.append(
            PythonCodeError(
                self.error_type,
                message,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
            )
        )

    def validate(self, tree: ast.AST) -> list[PythonCodeError]:
        self.visit(tree)
        return self.errors


class _PolicyValidator(_ValidationVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.function_names: set[str] = set()
        self.call_stack: list[str] = []
        self.call_edges: dict[str, set[str]] = {}

    def validate(self, tree: ast.AST) -> list[PythonCodeError]:
        self.function_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        super().validate(tree)
        for function_name in self.function_names:
            if _call_graph_reaches(
                self.call_edges,
                start=function_name,
                target=function_name,
            ):
                self.errors.append(
                    PythonCodeError(
                        "PolicyError",
                        f"recursive call cycle involving {function_name!r} is forbidden",
                    )
                )
        return self.errors

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in _ALLOWED_IMPORTS:
                self.fail(node, f"import {alias.name!r} is outside the whitelist")
            if alias.asname is not None:
                self.fail(node, "import aliases are outside the auditable subset")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        names = {alias.name for alias in node.names}
        if module != "exp_graph.llm.factory" or names != {"create_llm_client"}:
            self.fail(node, f"from-import {module!r} is outside the whitelist")
        if any(alias.asname is not None for alias in node.names):
            self.fail(node, "factory import aliases are forbidden")

    def visit_While(self, node: ast.While) -> None:
        self.fail(node, "while loops are forbidden; use bounded for/range")

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.fail(node, "async execution is forbidden")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.fail(node, "async functions are forbidden")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.fail(node, "class definitions are outside the auditable subset")

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.fail(node, "lambda is outside the auditable subset")

    def visit_With(self, node: ast.With) -> None:
        self.fail(node, "context managers are outside the auditable subset")

    def visit_Try(self, node: ast.Try) -> None:
        self.fail(node, "exception handlers may not swallow safety/budget failures")

    def visit_Global(self, node: ast.Global) -> None:
        self.fail(node, "global mutation is forbidden")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.fail(node, "nonlocal mutation is forbidden")

    def visit_Delete(self, node: ast.Delete) -> None:
        self.fail(node, "delete is outside the auditable subset")

    def visit_Pass(self, node: ast.Pass) -> None:
        self.fail(node, "pass placeholders are outside the executable subset")

    def visit_Yield(self, node: ast.Yield) -> None:
        self.fail(node, "generators are outside the auditable subset")

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.fail(node, "generators are outside the auditable subset")

    def visit_Await(self, node: ast.Await) -> None:
        self.fail(node, "async execution is forbidden")

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.fail(node, "assignment expressions are outside the auditable subset")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self.call_stack:
            self.fail(node, "nested functions are outside the auditable subset")
        if node.decorator_list:
            self.fail(node, "function decorators are forbidden")
        if node.args.vararg is not None or node.args.kwarg is not None:
            self.fail(node, "variadic functions are outside the auditable subset")
        if node.name in {"create_llm_client", "json", "sys"}:
            self.fail(node, f"protected name {node.name!r} may not be shadowed")
        self.call_stack.append(node.name)
        self.generic_visit(node)
        self.call_stack.pop()

    def visit_For(self, node: ast.For) -> None:
        if not _is_bounded_iterator(node.iter):
            self.fail(node, "for loop iterator is not statically bounded")
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if node.is_async or not _is_bounded_iterator(node.iter):
            self.fail(node, "comprehension iterator is not statically bounded")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                self.fail(target, "attribute assignment and monkey patching are forbidden")
            if isinstance(target, ast.Name) and target.id in {
                "create_llm_client",
                "json",
                "sys",
            }:
                self.fail(target, f"protected name {target.id!r} may not be reassigned")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Attribute):
            self.fail(node.target, "attribute assignment and monkey patching are forbidden")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_NAMES or (
            node.id.startswith("__") and node.id.endswith("__")
        ):
            self.fail(node, f"name {node.id!r} is forbidden")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr.startswith("_")
            or node.attr in _FORBIDDEN_ATTRIBUTE_NAMES
        ):
            self.fail(node, f"attribute {node.attr!r} is forbidden")
        root = _attribute_name(node).split(".", 1)[0]
        if root == "client" and node.attr != "complete":
            self.fail(node, "the authorized client exposes only complete")
        if root == "sys" and node.attr not in {"stdin", "stdout", "write"}:
            self.fail(node, f"sys attribute {node.attr!r} is outside the whitelist")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name in _FORBIDDEN_NAMES:
            self.fail(node, f"call to {name!r} is forbidden")
        if self.call_stack and name == self.call_stack[-1]:
            self.fail(node, "recursive calls are forbidden")
        if self.call_stack and name in self.function_names:
            self.call_edges.setdefault(self.call_stack[-1], set()).add(name)
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _FORBIDDEN_MODULE_PREFIXES):
            self.fail(node, f"call through forbidden module {name!r}")
        self.generic_visit(node)


class _APIValidator(_ValidationVisitor):
    error_type: PythonErrorType = "APIError"

    def __init__(self) -> None:
        super().__init__()
        self.factory_calls = 0
        self.complete_calls = 0
        self.stdin_reads = 0
        self.stdout_writes = 0
        self.payload_assignments = 0
        self.worker_cfg_assignments = 0
        self.agents_assignments = 0
        self.client_assignments = 0

    def validate(self, tree: ast.AST) -> list[PythonCodeError]:
        super().validate(tree)
        if self.factory_calls != 1:
            self.errors.append(
                PythonCodeError(
                    "APIError",
                    "program must call create_llm_client exactly once",
                )
            )
        if self.complete_calls < 1:
            self.errors.append(
                PythonCodeError("APIError", "program must call LLMClient.complete")
            )
        if self.stdin_reads != 1:
            self.errors.append(
                PythonCodeError("APIError", "program must read stdin exactly once")
            )
        if self.stdout_writes != 1:
            self.errors.append(
                PythonCodeError(
                    "APIError",
                    "program must write exactly one JSON result to stdout",
                )
            )
        for count, message in (
            (self.payload_assignments, "payload must be assigned once from json.load(sys.stdin)"),
            (self.worker_cfg_assignments, "worker_cfg must be payload['worker_llm']"),
            (self.agents_assignments, "agents must be payload['agents']"),
            (self.client_assignments, "client must be the sole factory result"),
        ):
            if count != 1:
                self.errors.append(PythonCodeError("APIError", message))
        return self.errors

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if target == "payload":
                if _is_json_stdin_load(node.value):
                    self.payload_assignments += 1
                else:
                    self.fail(node, "payload may only come from json.load(sys.stdin)")
            elif target == "worker_cfg":
                if _is_named_lookup(node.value, "payload", "worker_llm"):
                    self.worker_cfg_assignments += 1
                else:
                    self.fail(node, "worker_cfg must be payload['worker_llm']")
            elif target == "agents":
                if _is_named_lookup(node.value, "payload", "agents"):
                    self.agents_assignments += 1
                else:
                    self.fail(node, "agents must be payload['agents']")
            elif target == "client":
                if isinstance(node.value, ast.Call) and (
                    _call_name(node.value) == "create_llm_client"
                ):
                    self.client_assignments += 1
                else:
                    self.fail(node, "client may only be the factory result")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name == "create_llm_client":
            self.factory_calls += 1
            if not node.args or not _is_named_lookup(
                node.args[0], "worker_cfg", "provider"
            ):
                self.fail(node, "provider must come unchanged from worker_llm payload")
            keyword_names = {kw.arg for kw in node.keywords}
            if not {"base_url", "api_key_env"}.issubset(keyword_names):
                self.fail(node, "factory must use payload base_url and api_key_env")
            for kw in node.keywords:
                if kw.arg in {"base_url", "api_key_env"} and not _is_named_lookup(
                    kw.value, "worker_cfg", kw.arg
                ):
                    self.fail(node, f"{kw.arg} must come unchanged from payload")
        elif name.endswith(".complete"):
            self.complete_calls += 1
            if name != "client.complete":
                self.fail(node, "complete must be called on the authorized client")
            if len(node.args) != 1:
                self.fail(node, "complete must receive exactly one prompt argument")
            keywords = {kw.arg: kw.value for kw in node.keywords}
            for required in ("model_name", "temperature"):
                if required not in keywords or not _is_named_lookup(
                    keywords[required], "worker_cfg", required
                ):
                    self.fail(node, f"complete {required} must come unchanged from payload")
        elif name == "json.load" and node.args and _is_sys_stdin(node.args[0]):
            self.stdin_reads += 1
        elif name in {"sys.stdout.write"}:
            self.stdout_writes += 1
            if (
                len(node.args) != 1
                or not isinstance(node.args[0], ast.Call)
                or _call_name(node.args[0]) != "json.dumps"
            ):
                self.fail(node, "stdout must receive exactly one json.dumps result")
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        # A bare expression that is not the one stdout write is usually a debug
        # or side-effect channel; calls are checked by the policy visitor.
        self.generic_visit(node)


class _DataFlowValidator(_ValidationVisitor):
    error_type: PythonErrorType = "DataFlowError"

    # Canonical worker-prompt headers demanded per worker contract. The
    # action_json_v1 tuple is exactly the historical requirement; the
    # message_only_v1 tuple pins the Planner-control/runtime-state headers the
    # bootstrap wrapper re-validates byte-for-byte at execution time.
    _REQUIRED_HEADERS: dict[str, tuple[str, ...]] = {
        "action_json_v1": (
            "PYTHON_AGENT_ID:",
            "PYTHON_ROUND:",
            "PREVIOUS_STATE_JSON:",
            "DELIVERED_INBOX_JSON:",
            "LOCAL_PROMPT:",
        ),
        "message_only_v1": (
            "PYTHON_WORKER_CONTRACT:",
            "PYTHON_AGENT_ID:",
            "PYTHON_ROUND:",
            "PYTHON_CONTROL_JSON:",
            "KNOWN_SOURCE_IDS_JSON:",
            "PREVIOUS_OUTPUT_JSON:",
            "DELIVERED_INBOX_JSON:",
            "LOCAL_PROMPT:",
        ),
        "message_only_v2": (
            "PYTHON_WORKER_CONTRACT:",
            "PYTHON_AGENT_ID:",
            "PYTHON_ROUND:",
            "PYTHON_SUBMIT_ROUND:",
            "PYTHON_CONTROL_JSON:",
            "KNOWN_SOURCE_IDS_JSON:",
            "PREVIOUS_OUTPUT_JSON:",
            "DELIVERED_INBOX_JSON:",
            "COMMUNICATION_PROMPT:",
            "SUBMIT_PROMPT:",
        ),
    }
    _PROMPT_FIELDS: dict[str, tuple[str, ...]] = {
        "action_json_v1": ("local_prompt",),
        "message_only_v1": ("local_prompt",),
        "message_only_v2": ("communication_prompt", "submit_prompt"),
    }

    def __init__(
        self,
        *,
        worker_contract: str = DEFAULT_PYTHON_WORKER_CONTRACT,
    ) -> None:
        super().__init__()
        self.worker_contract = worker_contract
        self.tainted_names: set[str] = set()
        self.prompt_accesses = {
            field: 0 for field in self._PROMPT_FIELDS[worker_contract]
        }
        self.seen_headers: set[str] = set()
        self.seen_contract_markers: set[str] = set()
        self.loop_stack: list[str] = []
        self.prompt_access_depth = 0

    def validate(self, tree: ast.AST) -> list[PythonCodeError]:
        super().validate(tree)
        for field, accesses in self.prompt_accesses.items():
            if accesses < 1:
                self.errors.append(
                    PythonCodeError(
                        "DataFlowError",
                        f"program never consumes per-agent {field}",
                    )
                )
        for header in self._REQUIRED_HEADERS[self.worker_contract]:
            if header not in self.seen_headers:
                self.errors.append(
                    PythonCodeError(
                        "DataFlowError",
                        f"worker prompts must include the canonical {header} header "
                        f"required by the {self.worker_contract} worker contract",
                    )
                )
        if self.worker_contract in {"message_only_v1", "message_only_v2"} and (
            self.seen_contract_markers != {self.worker_contract}
        ):
            self.errors.append(
                PythonCodeError(
                    "DataFlowError",
                    "worker prompt must declare exactly the selected message-only "
                    "contract",
                )
            )
        return self.errors

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        for header in self._REQUIRED_HEADERS[self.worker_contract]:
            if header in node.value:
                self.seen_headers.add(header)
        for contract in ("message_only_v1", "message_only_v2"):
            if f"PYTHON_WORKER_CONTRACT:{contract}" in node.value:
                self.seen_contract_markers.add(contract)

    def visit_For(self, node: ast.For) -> None:
        name = node.target.id if isinstance(node.target, ast.Name) else ""
        self.loop_stack.append(name)
        self.generic_visit(node)
        self.loop_stack.pop()

    def visit_Subscript(self, node: ast.Subscript) -> None:
        private_access = _private_prompt_agent_access(node)
        if private_access is not None:
            field, agent_index = private_access
            if field not in self.prompt_accesses:
                self.fail(
                    node,
                    f"{field} is not available under the {self.worker_contract} "
                    "worker contract",
                )
            else:
                self.prompt_accesses[field] += 1
            if not isinstance(agent_index, ast.Name) or agent_index.id != "agent_id":
                self.fail(
                    node,
                    f"{field} must be indexed only by the current agent_id",
                )
            elif "agent_id" not in self.loop_stack:
                self.fail(
                    node,
                    f"{field} access must occur inside the bounded agent_id loop",
                )
            self.prompt_access_depth += 1
            self.generic_visit(node)
            self.prompt_access_depth -= 1
            return
        if self.prompt_access_depth == 0 and _subscript_root_name(node) == "agents":
            allowed = ", ".join(self._PROMPT_FIELDS[self.worker_contract])
            self.fail(
                node,
                "agents payload may only access the current agent's authorized "
                f"prompt field(s): {allowed}",
            )
        if self.prompt_access_depth == 0 and _is_named_lookup(
            node, "payload", "agents"
        ):
            self.fail(node, "payload['agents'] may only initialize the canonical alias")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "agents"
            and _is_named_lookup(node.value, "payload", "agents")
        ):
            return
        if isinstance(node.value, ast.Name) and node.value.id == "agents":
            self.fail(node, "the agents container may not be aliased")
        declassified_worker_output = (
            isinstance(node.value, ast.Call)
            and _call_name(node.value).endswith(".complete")
        )
        tainted = not declassified_worker_output and (
            _contains_private_prompt(node.value)
            or _contains_name(node.value, self.tainted_names)
        )
        if tainted:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.tainted_names.add(target.id)
                    if target.id in {
                        "message",
                        "body",
                        "state",
                        "answer",
                        "output",
                        "result",
                    }:
                        self.fail(
                            node,
                            f"tainted private prompt may not flow into {target.id}",
                        )
                else:
                    self.fail(
                        node,
                        "tainted private prompt may not flow into a container or attribute",
                    )
        if _count_private_prompt_accesses(node.value) > 1:
            prompt_label = (
                "local prompts"
                if self._PROMPT_FIELDS[self.worker_contract] == ("local_prompt",)
                else "private prompts"
            )
            self.fail(node, f"multiple {prompt_label} may not be combined")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name == "payload.get" and any(
            isinstance(arg, ast.Constant) and arg.value == "agents"
            for arg in node.args
        ):
            self.fail(node, "payload agents may not be accessed through get")
        tainted = any(
            _contains_private_prompt(arg) or _contains_name(arg, self.tainted_names)
            for arg in node.args
        )
        if tainted and not name.endswith(".complete"):
            # Prompt text crosses only the authorized Worker-call boundary;
            # parsing or transforming it inside generated code is rejected.
            self.fail(node, f"tainted private prompt flows through call {name!r}")
        if name.endswith(".complete") and not tainted:
            self.fail(node, "every worker call must consume an authorized prompt")
        if isinstance(node.func, ast.Attribute) and node.func.attr in _TAINT_TRANSFORMS:
            if _contains_private_prompt(node.func.value) or _contains_name(
                node.func.value, self.tainted_names
            ):
                self.fail(
                    node,
                    f"private-prompt transformation {node.func.attr!r} is forbidden",
                )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value in {"message", "body", "state", "answer", "output"} and (
                _contains_private_prompt(value)
                or _contains_name(value, self.tainted_names)
            ):
                self.fail(node, f"private prompt may not flow into {key.value}")
        self.generic_visit(node)


def _is_bounded_iterator(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        call_name = _call_name(node)
        if call_name == "range":
            return bool(node.args) and all(_is_bounded_range_arg(arg) for arg in node.args)
        if call_name == "enumerate":
            return bool(node.args) and _is_bounded_iterator(node.args[0])
        if call_name.endswith(".get"):
            return _attribute_name(node.func.value) in {"delivered", "action"}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return True
    if isinstance(node, ast.Name) and node.id in {
        "pending",
        "messages",
        "recipients",
        "source_ids",
        "actions",
        "states",
        "inboxes",
        "snapshot_states",
        "snapshot_inboxes",
        "final_inboxes",
        "final_snapshot_states",
        "final_snapshot_inboxes",
        "submissions",
        "requested_recipients",
        "requested_sources",
    }:
        return True
    if isinstance(node, ast.Subscript):
        root = _subscript_root_name(node)
        return root in {
            "snapshot_inboxes",
            "final_snapshot_inboxes",
            "action",
            "delivered",
        }
    return False


def _is_bounded_range_arg(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return 0 <= node.value <= 10_000
    if isinstance(node, ast.Name):
        return node.id in {"n_agents", "max_rounds", "round_idx"}
    if isinstance(node, ast.Call) and _call_name(node) in {"len", "min", "max"}:
        return True
    return False


def _subscript_root_name(node: ast.Subscript) -> str:
    value: ast.AST = node
    while isinstance(value, ast.Subscript):
        value = value.value
    return value.id if isinstance(value, ast.Name) else ""


def _call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        prefix = _attribute_name(target.value)
        return f"{prefix}.{target.attr}" if prefix else target.attr
    return ""


def _attribute_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_named_lookup(node: ast.AST, name: str, key: str) -> bool:
    return bool(
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == name
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == key
    )


def _is_sys_stdin(node: ast.AST) -> bool:
    return bool(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
        and node.attr == "stdin"
    )


def _is_json_stdin_load(node: ast.AST) -> bool:
    return bool(
        isinstance(node, ast.Call)
        and _call_name(node) == "json.load"
        and len(node.args) == 1
        and _is_sys_stdin(node.args[0])
    )


def _call_graph_reaches(
    edges: dict[str, set[str]],
    *,
    start: str,
    target: str,
) -> bool:
    pending = list(edges.get(start, set()))
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(edges.get(current, set()))
    return False


_PRIVATE_PROMPT_FIELDS = frozenset(
    {"local_prompt", "communication_prompt", "submit_prompt"}
)


def _private_prompt_agent_access(
    node: ast.Subscript,
) -> tuple[str, ast.AST] | None:
    key = node.slice
    if (
        not isinstance(key, ast.Constant)
        or not isinstance(key.value, str)
        or key.value not in _PRIVATE_PROMPT_FIELDS
    ):
        return None
    agents_access = node.value
    if not isinstance(agents_access, ast.Subscript):
        return None
    if not isinstance(agents_access.value, ast.Name) or agents_access.value.id != "agents":
        return None
    return key.value, agents_access.slice


def _contains_private_prompt(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Subscript)
        and _private_prompt_agent_access(item) is not None
        for item in ast.walk(node)
    )


def _count_private_prompt_accesses(node: ast.AST) -> int:
    return sum(
        1
        for item in ast.walk(node)
        if isinstance(item, ast.Subscript)
        and _private_prompt_agent_access(item) is not None
    )


def _contains_name(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(item, ast.Name) and item.id in names for item in ast.walk(node))


# 中文：message_only_v1 的规范 Worker 指令。scaffold 与 bootstrap 包装器共用这两个
#   常量：包装器按控制模式逐字节重建期望提示词，任何偏离(包括改写指令区)都
#   fail closed——规范提示词是安全边界，生成程序不得借自由文本区走私他人信息。
# Canonical worker instructions for message_only_v1. The scaffold and the
# bootstrap wrapper share these constants: the wrapper rebuilds the expected
# prompt byte-for-byte per control mode, so any deviation (including an edited
# instruction region) fails closed — the canonical prompt is a security
# boundary and generated programs cannot smuggle peer information through a
# free-text region.
MESSAGE_ONLY_MESSAGE_INSTRUCTION = (
    "INSTRUCTION:\n"
    "The Planner already selected the routing action shown in "
    "PYTHON_CONTROL_JSON.\n"
    "Do not choose recipients, source ids, state, or submission flags.\n"
    "Return only the message body as plain text.\n"
    "Write a compact, self-contained rolling summary that keeps every fact "
    "needed later, including your own local information.\n"
    "Do not return JSON or Markdown.\n"
)
MESSAGE_ONLY_SUBMIT_INSTRUCTION = (
    "INSTRUCTION:\n"
    "The Planner already selected the submission action shown in "
    "PYTHON_CONTROL_JSON.\n"
    "Do not choose recipients, source ids, state, or submission flags.\n"
    "Return only this agent's final task answer as plain text.\n"
    "Do not return JSON, routing metadata, or Markdown, and add no "
    "explanation unless the task explicitly requires one.\n"
)

# message_only_v2 keeps communication text deliberately simple, but turns the
# final answer into a machine-readable boundary. The runtime parses the whole
# submit response with json.loads; no extractor or answer wrapper is involved.
MESSAGE_ONLY_V2_MESSAGE_INSTRUCTION = (
    "INSTRUCTION:\n"
    "This is a communication round. The Planner already selected the routing "
    "action shown in PYTHON_CONTROL_JSON.\n"
    "Do not choose recipients, source ids, state, submission timing, or answer "
    "format.\n"
    "Return only the message body as compact plain text.\n"
    "Keep every fact needed by a later final-answer call, including your own "
    "local information and useful delivered information.\n"
    "Do not return routing metadata or Markdown.\n"
)
MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION = (
    "FINAL OUTPUT CONTRACT:\n"
    "The communication phase is complete. This is the synchronized final "
    "submit round shown in PYTHON_SUBMIT_ROUND.\n"
    "Using only your local information, previous output, and delivered inbox "
    "from the frozen final snapshot, produce this agent's final benchmark "
    "answer.\n"
    "Match the public answer shape stated in PUBLIC_ANSWER_REQUIREMENT.\n"
    "Return exactly one valid JSON value and nothing else.\n"
    "For a text answer, include the JSON double quotes.\n"
    "Do not return a belief-state/status/proposal object, prose, Markdown, "
    "code fences, routing metadata, or an answer wrapper.\n"
    "Your entire response must be the single benchmark answer value.\n"
)


DEFAULT_PYTHON_PROGRAM = '''import json
import sys
from exp_graph.llm.factory import create_llm_client


def answer_from_action(action):
    answer = action.get("answer")
    if answer is None:
        structured = action.get("structured_state")
        if isinstance(structured, dict):
            answer = structured.get("answer")
    if answer is None:
        key = action.get("consensus_key")
        if key not in (None, "", "UNKNOWN"):
            answer = key
    return answer


def main():
    payload = json.load(sys.stdin)
    n_agents = int(payload["n_agents"])
    max_rounds = int(payload["max_rounds"])
    information_goal = payload["information_goal"]
    selected_primary = int(payload["selected_primary"])
    budgets = payload["budgets"]
    worker_cfg = payload["worker_llm"]
    agents = payload["agents"]
    client = create_llm_client(
        worker_cfg["provider"],
        base_url=worker_cfg["base_url"],
        api_key_env=worker_cfg["api_key_env"],
    )
    states = [{} for _ in range(n_agents)]
    pending = []
    messages = []
    submissions = [
        {"agent_id": agent_id, "answer": None, "submitted_round": None}
        for agent_id in range(n_agents)
    ]
    submitted = set()
    usage = {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    rounds_executed = 0

    for round_idx in range(max_rounds):
        active_count = 0
        for active_agent_id in range(n_agents):
            if active_agent_id not in submitted:
                active_count += 1
        if usage["model_calls"] + active_count > int(budgets["max_model_calls"]):
            break
        if usage["completion_tokens"] >= int(budgets["max_completion_tokens"]):
            break
        inboxes = [[] for _ in range(n_agents)]
        for message_item in pending:
            if int(message_item["round_delivered"]) == round_idx:
                inboxes[int(message_item["dst"])].append(message_item)
        snapshot_states = [dict(state_item) for state_item in states]
        snapshot_inboxes = [list(inbox_item) for inbox_item in inboxes]
        actions = []

        for agent_id in range(n_agents):
            if agent_id in submitted:
                actions.append(None)
            else:
                local_prompt = agents[agent_id]["local_prompt"]
                action_contract = (
                    "PYTHON_AGENT_ID:" + str(agent_id) + "\\n"
                    "PYTHON_ROUND:" + str(round_idx) + "\\n"
                    "Return one JSON action with state, should_send, recipients, "
                    "message, source_ids, submit, answer. Use only your local "
                    "prompt, previous state, and delivered inbox.\\n"
                    "PREVIOUS_STATE_JSON:" + json.dumps(snapshot_states[agent_id]) + "\\n"
                    "DELIVERED_INBOX_JSON:" + json.dumps(snapshot_inboxes[agent_id]) + "\\n"
                    "LOCAL_PROMPT:\\n"
                )
                worker_prompt = action_contract + local_prompt
                response = client.complete(
                    worker_prompt,
                    model_name=worker_cfg["model_name"],
                    temperature=worker_cfg["temperature"],
                )
                usage["model_calls"] += int(response.usage.model_calls)
                usage["prompt_tokens"] += int(response.usage.prompt_tokens)
                usage["completion_tokens"] += int(response.usage.completion_tokens)
                raw_action = json.loads(response.text)
                known_sources = set(snapshot_states[agent_id].get("source_ids", [agent_id]))
                known_sources.add(agent_id)
                for delivered in snapshot_inboxes[agent_id]:
                    for source_id in delivered.get("source_ids", []):
                        known_sources.add(int(source_id))

                if "should_send" in raw_action:
                    requested_state = raw_action.get("state", {})
                    requested_recipients = list(raw_action.get("recipients", []))
                    requested_sources = list(raw_action.get("source_ids", []))
                    if not isinstance(requested_state, dict):
                        raise ValueError("state must be an object")
                    for recipient in requested_recipients:
                        recipient_id = int(recipient)
                        if recipient_id < 0 or recipient_id >= n_agents or recipient_id == agent_id:
                            raise ValueError("invalid recipient")
                    for source_id in requested_sources:
                        normalized_source = int(source_id)
                        if normalized_source not in known_sources:
                            raise ValueError("invalid source provenance")
                    if agent_id not in requested_sources:
                        raise ValueError("source provenance must include sender")
                    if len(set(requested_sources)) != len(requested_sources):
                        raise ValueError("source provenance must be deduplicated")
                    action = {
                        "state": requested_state,
                        "should_send": bool(raw_action.get("should_send", False)),
                        "recipients": requested_recipients,
                        "message": raw_action.get("message"),
                        "source_ids": sorted(requested_sources),
                        "submit": bool(raw_action.get("submit", False)),
                        "answer": raw_action.get("answer"),
                    }
                else:
                    if information_goal == "sink":
                        fallback_recipients = [selected_primary] if agent_id != selected_primary else []
                    else:
                        fallback_recipients = [(agent_id + 1) % n_agents] if n_agents > 1 else []
                    fallback_send = bool(fallback_recipients)
                    if information_goal == "all_agents" and round_idx == 0 and agent_id == n_agents - 1:
                        fallback_send = False
                    action = {
                        "state": raw_action,
                        "should_send": fallback_send,
                        "recipients": fallback_recipients,
                        "message": raw_action,
                        "source_ids": sorted(known_sources),
                        "submit": round_idx + 1 >= max_rounds,
                        "answer": answer_from_action(raw_action),
                    }
                actions.append(action)

        next_states = [dict(state_item) for state_item in snapshot_states]
        next_pending = []
        for agent_id in range(n_agents):
            action = actions[agent_id]
            if action is not None:
                updated_state = dict(snapshot_states[agent_id])
                updated_state.update(action["state"])
                updated_state["source_ids"] = list(action["source_ids"])
                next_states[agent_id] = updated_state
                if action["submit"]:
                    submissions[agent_id] = {
                        "agent_id": agent_id,
                        "answer": action["answer"],
                        "submitted_round": round_idx,
                    }
                    submitted.add(agent_id)
                if action["should_send"] and agent_id not in submitted:
                    for recipient in action["recipients"]:
                        if len(messages) >= int(budgets["max_messages"]):
                            break
                        recipient_id = int(recipient)
                        message_item = {
                            "round_sent": round_idx,
                            "round_delivered": round_idx + 1,
                            "src": agent_id,
                            "dst": recipient_id,
                            "source_ids": list(action["source_ids"]),
                            "body": action["message"],
                        }
                        messages.append(message_item)
                        next_pending.append(message_item)
        states = next_states
        pending = next_pending
        rounds_executed = round_idx + 1
        if information_goal == "sink" and selected_primary in submitted:
            break
        if information_goal == "all_agents" and len(submitted) == n_agents:
            break
        if usage["model_calls"] >= int(budgets["max_model_calls"]):
            break
        if usage["completion_tokens"] >= int(budgets["max_completion_tokens"]):
            break
        if len(messages) >= int(budgets["max_messages"]):
            break

    output = {
        "submissions": submissions,
        "rounds_executed": rounds_executed,
        "messages": messages,
        "usage": usage,
        "errors": [],
    }
    sys.stdout.write(json.dumps(output))


main()
'''


# 中文：message_only_v1 的已验证 scaffold。职责划分：plan_turn(Planner source)决定
#   send/reflect/submit/idle 与 recipients；宿主/Runtime 维护 previous_output、
#   source_ids 合并、延迟一轮投递与预算；Worker 只返回纯文本(json_mode=False)。
#   Worker 永不填写 state/recipients/source_ids/submit 字段。
# The verified message_only_v1 scaffold. Responsibility split: plan_turn (the
# Planner source) picks send/reflect/submit/idle plus recipients; the
# host/runtime owns previous_output, source-id merging, one-round delivery
# delay and budgets; the worker only returns plain text (json_mode=False) and
# never authors state/recipients/source_ids/submit fields.
DEFAULT_MESSAGE_ONLY_PROGRAM = (
    '''import json
import sys
from exp_graph.llm.factory import create_llm_client


MESSAGE_INSTRUCTION = '''
    + repr(MESSAGE_ONLY_MESSAGE_INSTRUCTION)
    + '''
SUBMIT_INSTRUCTION = '''
    + repr(MESSAGE_ONLY_SUBMIT_INSTRUCTION)
    + '''


def plan_turn(
    round_idx,
    agent_id,
    n_agents,
    max_rounds,
    information_goal,
    selected_primary,
    known_source_count,
    inbox_count,
):
    if information_goal == "sink":
        if agent_id == selected_primary and (
            known_source_count == n_agents or round_idx + 1 >= max_rounds
        ):
            return {"mode": "submit", "recipients": []}
    else:
        if known_source_count == n_agents or round_idx + 1 >= max_rounds:
            return {"mode": "submit", "recipients": []}
    if round_idx + 1 >= max_rounds:
        return {"mode": "idle", "recipients": []}
    if information_goal == "sink":
        if agent_id == selected_primary:
            return {"mode": "idle", "recipients": []}
        if round_idx == 0:
            return {"mode": "send", "recipients": [selected_primary]}
        return {"mode": "idle", "recipients": []}
    if n_agents == 1:
        return {"mode": "reflect", "recipients": []}
    return {"mode": "send", "recipients": [(agent_id + 1) % n_agents]}


def main():
    payload = json.load(sys.stdin)
    n_agents = int(payload["n_agents"])
    max_rounds = int(payload["max_rounds"])
    information_goal = payload["information_goal"]
    selected_primary = int(payload["selected_primary"])
    budgets = payload["budgets"]
    worker_cfg = payload["worker_llm"]
    agents = payload["agents"]
    client = create_llm_client(
        worker_cfg["provider"],
        base_url=worker_cfg["base_url"],
        api_key_env=worker_cfg["api_key_env"],
    )
    states = [
        {"previous_output": "", "source_ids": [agent_id]}
        for agent_id in range(n_agents)
    ]
    pending = []
    messages = []
    submissions = [
        {"agent_id": agent_id, "answer": None, "submitted_round": None}
        for agent_id in range(n_agents)
    ]
    submitted = set()
    usage = {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    rounds_executed = 0

    for round_idx in range(max_rounds):
        inboxes = [[] for _ in range(n_agents)]
        for message_item in pending:
            if int(message_item["round_delivered"]) == round_idx:
                inboxes[int(message_item["dst"])].append(message_item)
        snapshot_inboxes = [list(inbox_item) for inbox_item in inboxes]
        snapshot_states = [dict(state_item) for state_item in states]
        for agent_id in range(n_agents):
            merged_sources = list(snapshot_states[agent_id]["source_ids"])
            for delivered in snapshot_inboxes[agent_id]:
                for source_id in delivered["source_ids"]:
                    merged_sources.append(int(source_id))
            snapshot_states[agent_id] = {
                "previous_output": snapshot_states[agent_id]["previous_output"],
                "source_ids": sorted(set(merged_sources)),
            }
        actions = []
        planned_calls = 0
        planned_sends = 0
        for agent_id in range(n_agents):
            if agent_id in submitted:
                actions.append(None)
            else:
                action = plan_turn(
                    round_idx,
                    agent_id,
                    n_agents,
                    max_rounds,
                    information_goal,
                    selected_primary,
                    len(snapshot_states[agent_id]["source_ids"]),
                    len(snapshot_inboxes[agent_id]),
                )
                mode = str(action["mode"])
                recipients = [int(recipient) for recipient in action["recipients"]]
                if mode not in ("send", "reflect", "submit", "idle"):
                    raise ValueError("DataFlowError: unknown planner control mode")
                if mode != "send" and recipients:
                    raise ValueError("DataFlowError: recipients require send mode")
                if len(set(recipients)) != len(recipients):
                    raise ValueError("DataFlowError: duplicate recipients")
                for recipient in recipients:
                    if recipient < 0 or recipient >= n_agents or recipient == agent_id:
                        raise ValueError("DataFlowError: recipient outside the agent range")
                actions.append({"mode": mode, "recipients": recipients})
                if mode != "idle":
                    planned_calls += 1
                planned_sends += len(recipients)
        if usage["model_calls"] + planned_calls > int(budgets["max_model_calls"]):
            break
        if usage["completion_tokens"] >= int(budgets["max_completion_tokens"]):
            break
        if len(messages) + planned_sends > int(budgets["max_messages"]):
            break

        next_states = [dict(state_item) for state_item in snapshot_states]
        next_pending = []
        called_any = False
        for agent_id in range(n_agents):
            action = actions[agent_id]
            if action is None:
                continue
            if action["mode"] == "idle":
                continue
            if action["mode"] == "submit":
                instruction = SUBMIT_INSTRUCTION
            else:
                instruction = MESSAGE_INSTRUCTION
            local_prompt = agents[agent_id]["local_prompt"]
            control_header = (
                "PYTHON_WORKER_CONTRACT:message_only_v1\\n"
                "PYTHON_AGENT_ID:" + str(agent_id) + "\\n"
                "PYTHON_ROUND:" + str(round_idx) + "\\n"
                "PYTHON_CONTROL_JSON:" + json.dumps(action, sort_keys=True) + "\\n"
                "KNOWN_SOURCE_IDS_JSON:"
                + json.dumps(snapshot_states[agent_id]["source_ids"]) + "\\n"
                "PREVIOUS_OUTPUT_JSON:"
                + json.dumps(snapshot_states[agent_id]["previous_output"]) + "\\n"
                "DELIVERED_INBOX_JSON:"
                + json.dumps(snapshot_inboxes[agent_id], sort_keys=True) + "\\n"
                + instruction
                + "LOCAL_PROMPT:\\n"
            )
            worker_prompt = control_header + local_prompt
            response = client.complete(
                worker_prompt,
                model_name=worker_cfg["model_name"],
                temperature=worker_cfg["temperature"],
                json_mode=False,
            )
            usage["model_calls"] += int(response.usage.model_calls)
            usage["prompt_tokens"] += int(response.usage.prompt_tokens)
            usage["completion_tokens"] += int(response.usage.completion_tokens)
            worker_output = response.text.strip()
            called_any = True
            if action["mode"] == "submit":
                submissions[agent_id] = {
                    "agent_id": agent_id,
                    "answer": worker_output,
                    "submitted_round": round_idx,
                }
                submitted.add(agent_id)
            else:
                next_states[agent_id] = {
                    "previous_output": worker_output,
                    "source_ids": list(snapshot_states[agent_id]["source_ids"]),
                }
            if action["mode"] == "send":
                for recipient in action["recipients"]:
                    message_item = {
                        "round_sent": round_idx,
                        "round_delivered": round_idx + 1,
                        "src": agent_id,
                        "dst": int(recipient),
                        "source_ids": list(snapshot_states[agent_id]["source_ids"]),
                        "body": worker_output,
                    }
                    messages.append(message_item)
                    next_pending.append(message_item)
        states = next_states
        pending = next_pending
        if called_any:
            rounds_executed = round_idx + 1
        if len(submitted) == n_agents:
            break
        if information_goal == "sink" and selected_primary in submitted:
            break

    output = {
        "submissions": submissions,
        "rounds_executed": rounds_executed,
        "messages": messages,
        "usage": usage,
        "errors": [],
    }
    sys.stdout.write(json.dumps(output))


main()
'''
)


# message_only_v2 is a separate executable scaffold. The Planner controls only
# communication; the runtime-owned final barrier is intentionally outside the
# editable communication policy so no agent can submit early.
DEFAULT_MESSAGE_ONLY_V2_PROGRAM = (
    '''import json
import sys
from exp_graph.llm.factory import create_llm_client


MESSAGE_INSTRUCTION = '''
    + repr(MESSAGE_ONLY_V2_MESSAGE_INSTRUCTION)
    + '''
SUBMIT_INSTRUCTION = '''
    + repr(MESSAGE_ONLY_V2_SUBMIT_INSTRUCTION)
    + '''


def reject_nonfinite(value):
    raise ValueError("AnswerFormatError: non-finite JSON constants are forbidden")


def plan_submit_round(n_agents, max_rounds, information_goal):
    return max_rounds - 1


def plan_communication_turn(
    round_idx,
    agent_id,
    n_agents,
    information_goal,
    selected_primary,
    known_source_count,
    inbox_count,
):
    if information_goal == "sink":
        if agent_id == selected_primary:
            if inbox_count:
                return {"mode": "reflect", "recipients": []}
            return {"mode": "idle", "recipients": []}
        if round_idx == 0:
            return {"mode": "send", "recipients": [selected_primary]}
        return {"mode": "idle", "recipients": []}
    if n_agents == 1:
        return {"mode": "reflect", "recipients": []}
    recipients = []
    for recipient in range(n_agents):
        if recipient != agent_id:
            recipients.append(recipient)
    return {"mode": "send", "recipients": recipients}


def main():
    payload = json.load(sys.stdin)
    n_agents = int(payload["n_agents"])
    max_rounds = int(payload["max_rounds"])
    information_goal = payload["information_goal"]
    selected_primary = int(payload["selected_primary"])
    budgets = payload["budgets"]
    worker_cfg = payload["worker_llm"]
    agents = payload["agents"]
    client = create_llm_client(
        worker_cfg["provider"],
        base_url=worker_cfg["base_url"],
        api_key_env=worker_cfg["api_key_env"],
    )
    submit_round = int(
        plan_submit_round(n_agents, max_rounds, information_goal)
    )
    if submit_round < 0 or submit_round >= max_rounds:
        raise ValueError("DataFlowError: submit round outside the round budget")
    states = [
        {"previous_output": "", "source_ids": [agent_id]}
        for agent_id in range(n_agents)
    ]
    pending = []
    messages = []
    submissions = [
        {"agent_id": agent_id, "answer": None, "submitted_round": None}
        for agent_id in range(n_agents)
    ]
    usage = {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    for round_idx in range(max_rounds):
        if round_idx >= submit_round:
            continue
        inboxes = [[] for _ in range(n_agents)]
        for message_item in pending:
            if int(message_item["round_delivered"]) == round_idx:
                inboxes[int(message_item["dst"])].append(message_item)
        snapshot_inboxes = [list(inbox_item) for inbox_item in inboxes]
        snapshot_states = [dict(state_item) for state_item in states]
        for agent_id in range(n_agents):
            merged_sources = list(snapshot_states[agent_id]["source_ids"])
            for delivered in snapshot_inboxes[agent_id]:
                for source_id in delivered["source_ids"]:
                    merged_sources.append(int(source_id))
            snapshot_states[agent_id] = {
                "previous_output": snapshot_states[agent_id]["previous_output"],
                "source_ids": sorted(set(merged_sources)),
            }
        actions = []
        planned_calls = 0
        planned_sends = 0
        for agent_id in range(n_agents):
            action = plan_communication_turn(
                round_idx,
                agent_id,
                n_agents,
                information_goal,
                selected_primary,
                len(snapshot_states[agent_id]["source_ids"]),
                len(snapshot_inboxes[agent_id]),
            )
            mode = str(action["mode"])
            recipients = [int(recipient) for recipient in action["recipients"]]
            if mode not in ("send", "reflect", "idle"):
                raise ValueError(
                    "DataFlowError: communication policy cannot submit"
                )
            if mode != "send" and recipients:
                raise ValueError("DataFlowError: recipients require send mode")
            if len(set(recipients)) != len(recipients):
                raise ValueError("DataFlowError: duplicate recipients")
            for recipient in recipients:
                if recipient < 0 or recipient >= n_agents or recipient == agent_id:
                    raise ValueError(
                        "DataFlowError: recipient outside the agent range"
                    )
            actions.append({"mode": mode, "recipients": recipients})
            if mode != "idle":
                planned_calls += 1
            planned_sends += len(recipients)
        if usage["model_calls"] + planned_calls > int(budgets["max_model_calls"]):
            raise ValueError("BudgetError: communication call budget exhausted")
        if usage["completion_tokens"] >= int(budgets["max_completion_tokens"]):
            raise ValueError("BudgetError: completion token budget exhausted")
        if len(messages) + planned_sends > int(budgets["max_messages"]):
            raise ValueError("BudgetError: communication message budget exhausted")

        next_states = [dict(state_item) for state_item in snapshot_states]
        next_pending = []
        for agent_id in range(n_agents):
            action = actions[agent_id]
            if action["mode"] == "idle":
                continue
            communication_prompt = agents[agent_id]["communication_prompt"]
            control_header = (
                "PYTHON_WORKER_CONTRACT:message_only_v2\\n"
                "PYTHON_AGENT_ID:" + str(agent_id) + "\\n"
                "PYTHON_ROUND:" + str(round_idx) + "\\n"
                "PYTHON_SUBMIT_ROUND:" + str(submit_round) + "\\n"
                "PYTHON_CONTROL_JSON:" + json.dumps(action, sort_keys=True) + "\\n"
                "KNOWN_SOURCE_IDS_JSON:"
                + json.dumps(snapshot_states[agent_id]["source_ids"]) + "\\n"
                "PREVIOUS_OUTPUT_JSON:"
                + json.dumps(snapshot_states[agent_id]["previous_output"]) + "\\n"
                "DELIVERED_INBOX_JSON:"
                + json.dumps(snapshot_inboxes[agent_id], sort_keys=True) + "\\n"
                + "COMMUNICATION_PROMPT:\\n"
            )
            worker_prompt = (
                control_header + communication_prompt + "\\n" + MESSAGE_INSTRUCTION
            )
            response = client.complete(
                worker_prompt,
                model_name=worker_cfg["model_name"],
                temperature=worker_cfg["temperature"],
                json_mode=False,
            )
            usage["model_calls"] += int(response.usage.model_calls)
            usage["prompt_tokens"] += int(response.usage.prompt_tokens)
            usage["completion_tokens"] += int(response.usage.completion_tokens)
            worker_output = response.text.strip()
            next_states[agent_id] = {
                "previous_output": worker_output,
                "source_ids": list(snapshot_states[agent_id]["source_ids"]),
            }
            if action["mode"] == "send":
                for recipient in action["recipients"]:
                    message_item = {
                        "round_sent": round_idx,
                        "round_delivered": round_idx + 1,
                        "src": agent_id,
                        "dst": int(recipient),
                        "source_ids": list(snapshot_states[agent_id]["source_ids"]),
                        "body": worker_output,
                    }
                    messages.append(message_item)
                    next_pending.append(message_item)
        states = next_states
        pending = next_pending

    final_inboxes = [[] for _ in range(n_agents)]
    for message_item in pending:
        if int(message_item["round_delivered"]) == submit_round:
            final_inboxes[int(message_item["dst"])].append(message_item)
    final_snapshot_inboxes = [list(inbox_item) for inbox_item in final_inboxes]
    final_snapshot_states = [dict(state_item) for state_item in states]
    for agent_id in range(n_agents):
        merged_sources = list(final_snapshot_states[agent_id]["source_ids"])
        for delivered in final_snapshot_inboxes[agent_id]:
            for source_id in delivered["source_ids"]:
                merged_sources.append(int(source_id))
        final_snapshot_states[agent_id] = {
            "previous_output": final_snapshot_states[agent_id]["previous_output"],
            "source_ids": sorted(set(merged_sources)),
        }

    submit_count = n_agents
    if information_goal == "sink":
        submit_count = 1
    if usage["model_calls"] + submit_count > int(budgets["max_model_calls"]):
        raise ValueError("BudgetError: synchronized submit call budget exhausted")
    if (
        int(budgets["max_completion_tokens"]) - usage["completion_tokens"]
        < submit_count
    ):
        raise ValueError("BudgetError: synchronized submit token budget exhausted")

    for agent_id in range(n_agents):
        if information_goal == "sink" and agent_id != selected_primary:
            continue
        action = {"mode": "submit", "recipients": []}
        submit_prompt = agents[agent_id]["submit_prompt"]
        control_header = (
            "PYTHON_WORKER_CONTRACT:message_only_v2\\n"
            "PYTHON_AGENT_ID:" + str(agent_id) + "\\n"
            "PYTHON_ROUND:" + str(submit_round) + "\\n"
            "PYTHON_SUBMIT_ROUND:" + str(submit_round) + "\\n"
            "PYTHON_CONTROL_JSON:" + json.dumps(action, sort_keys=True) + "\\n"
            "KNOWN_SOURCE_IDS_JSON:"
            + json.dumps(final_snapshot_states[agent_id]["source_ids"]) + "\\n"
            "PREVIOUS_OUTPUT_JSON:"
            + json.dumps(final_snapshot_states[agent_id]["previous_output"]) + "\\n"
            "DELIVERED_INBOX_JSON:"
            + json.dumps(final_snapshot_inboxes[agent_id], sort_keys=True) + "\\n"
            + "SUBMIT_PROMPT:\\n"
        )
        worker_prompt = control_header + submit_prompt + "\\n" + SUBMIT_INSTRUCTION
        response = client.complete(
            worker_prompt,
            model_name=worker_cfg["model_name"],
            temperature=worker_cfg["temperature"],
            json_mode=False,
        )
        usage["model_calls"] += int(response.usage.model_calls)
        usage["prompt_tokens"] += int(response.usage.prompt_tokens)
        usage["completion_tokens"] += int(response.usage.completion_tokens)
        worker_output = response.text.strip()
        answer = json.loads(worker_output, parse_constant=reject_nonfinite)
        submissions[agent_id] = {
            "agent_id": agent_id,
            "answer": answer,
            "submitted_round": submit_round,
        }

    output = {
        "submissions": submissions,
        "rounds_executed": submit_round + 1,
        "messages": messages,
        "usage": usage,
        "errors": [],
    }
    sys.stdout.write(json.dumps(output))


main()
'''
)


def default_python_program(
    worker_contract: str = DEFAULT_PYTHON_WORKER_CONTRACT,
) -> str:
    """Return the verified scaffold source for one worker contract, fail closed."""
    if worker_contract == "action_json_v1":
        return DEFAULT_PYTHON_PROGRAM
    if worker_contract == "message_only_v1":
        return DEFAULT_MESSAGE_ONLY_PROGRAM
    if worker_contract == "message_only_v2":
        return DEFAULT_MESSAGE_ONLY_V2_PROGRAM
    raise ValueError(f"unknown python worker contract {worker_contract!r}")
