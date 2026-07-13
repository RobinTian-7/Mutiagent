"""Safe, bounded topology programs for LLM-generated communication graphs.

The language is deliberately smaller than Python.  An emperor may describe
literal edges, finite repeat loops, per-edge agent loops, and predicates.  The
compiler interprets a whitelisted integer expression AST and expands the
program to ordinary simultaneous communication steps.  No model output is ever
passed to ``eval`` or ``exec``.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Iterator
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator


TOPOLOGY_PROGRAM_FORMAT = "topology_program_v1"
TOPOLOGY_PROGRAM_COMPILER_VERSION = "1"

ScalarExpression: TypeAlias = int | str
PredicateExpression: TypeAlias = bool | str

_EXPRESSION_FUNCTIONS = {
    "abs",
    "ceil_log2",
    "floor_log2",
    "max",
    "min",
    "pow2",
}
_RESERVED_VARIABLES = {"n_agents", *_EXPRESSION_FUNCTIONS}


class TopologyProgramError(ValueError):
    """A topology program is unsafe, invalid, or exceeds expansion limits."""


class TopologyRangeSpec(BaseModel):
    """A finite integer range with Python's stop-exclusive semantics."""

    model_config = ConfigDict(extra="forbid")

    start: ScalarExpression = 0
    stop: ScalarExpression
    step: ScalarExpression = 1


class TopologyLoopSpec(BaseModel):
    """One named loop binding available to expressions in its body."""

    model_config = ConfigDict(extra="forbid")

    var: str
    range: TopologyRangeSpec

    @field_validator("var")
    @classmethod
    def validate_var(cls, value: str) -> str:
        name = value.strip()
        if (
            not name.isidentifier()
            or name.startswith("_")
            or name in _RESERVED_VARIABLES
        ):
            raise ValueError(f"invalid topology loop variable: {value!r}")
        return name


class TopologyEdgeTemplate(BaseModel):
    """One edge expression, optionally expanded over finite agent loops."""

    model_config = ConfigDict(extra="forbid")

    src: ScalarExpression
    dst: ScalarExpression
    when: PredicateExpression = True
    for_each: list[TopologyLoopSpec] = Field(default_factory=list)


class TopologyStepStatement(BaseModel):
    """One simultaneous round produced by a topology program."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["step"] = "step"
    description: str = ""
    operator_hint: str = "program_generated"
    instruction: str | None = None
    edges: list[TopologyEdgeTemplate] = Field(min_length=1)


class TopologyRepeatStatement(BaseModel):
    """Repeat one or more sequential communication steps over a finite range."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["repeat"] = "repeat"
    var: str
    range: TopologyRangeSpec
    body: list[TopologyStepStatement] = Field(min_length=1)

    @field_validator("var")
    @classmethod
    def validate_var(cls, value: str) -> str:
        return TopologyLoopSpec.validate_var(value)


TopologyStatement: TypeAlias = Annotated[
    TopologyStepStatement | TopologyRepeatStatement,
    Field(discriminator="op"),
]


class TopologyProgram(BaseModel):
    """Versioned declarative source for a finite temporal topology."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["topology_program_v1"] = TOPOLOGY_PROGRAM_FORMAT
    selected_primary: ScalarExpression | None = None
    body: list[TopologyStatement] = Field(min_length=1)


class TopologyProgramLimits(BaseModel):
    """Hard limits that make expansion finite and inexpensive."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=64, gt=0)
    max_messages: int = Field(default=4096, ge=0)
    max_loop_iterations: int = Field(default=1024, gt=0)
    max_expansion_operations: int = Field(default=10000, gt=0)
    max_expression_length: int = Field(default=200, gt=0)
    max_expression_nodes: int = Field(default=64, gt=0)
    max_abs_integer: int = Field(default=1_000_000, gt=0)


class CompiledTopologyStep(BaseModel):
    """One expanded simultaneous communication round."""

    description: str = ""
    operator_hint: str = "program_generated"
    instruction: str | None = None
    edges: list[tuple[int, int]] = Field(default_factory=list)


class CompiledTopologyProgram(BaseModel):
    """Finite result produced by the topology program compiler."""

    format: Literal["topology_program_v1"] = TOPOLOGY_PROGRAM_FORMAT
    compiler_version: str = TOPOLOGY_PROGRAM_COMPILER_VERSION
    source_hash: str
    selected_primary: int | None = None
    steps: list[CompiledTopologyStep] = Field(default_factory=list)
    expanded_messages: int = 0
    warnings: list[str] = Field(default_factory=list)


def topology_program_digest(program: TopologyProgram) -> str:
    """Return a stable digest for the declarative source, before expansion."""
    payload = json.dumps(
        program.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compile_topology_program(
    program: TopologyProgram,
    *,
    n_agents: int,
    limits: TopologyProgramLimits | None = None,
) -> CompiledTopologyProgram:
    """Safely expand a declarative program into finite communication steps."""
    if n_agents < 1:
        raise TopologyProgramError("n_agents must be positive")
    compiler = _TopologyProgramCompiler(
        n_agents=n_agents,
        limits=limits or TopologyProgramLimits(),
    )
    return compiler.compile(program)


class _TopologyProgramCompiler:
    def __init__(self, *, n_agents: int, limits: TopologyProgramLimits) -> None:
        self.n_agents = n_agents
        self.limits = limits
        self.evaluator = _ExpressionEvaluator(limits)
        self.steps: list[CompiledTopologyStep] = []
        self.total_messages = 0
        self.expansion_operations = 0
        self.warnings: list[str] = []

    def compile(self, program: TopologyProgram) -> CompiledTopologyProgram:
        base_env = {"n_agents": self.n_agents}
        for statement_idx, statement in enumerate(program.body):
            path = f"body[{statement_idx}]"
            if isinstance(statement, TopologyStepStatement):
                self._compile_step(statement, base_env, path)
            else:
                self._compile_repeat(statement, base_env, path)
        if not self.steps:
            raise TopologyProgramError(
                "topology program produced no communication steps"
            )
        selected_primary = None
        if program.selected_primary is not None:
            selected_primary = self.evaluator.evaluate_int(
                program.selected_primary,
                base_env,
                label="selected_primary",
            )
        return CompiledTopologyProgram(
            source_hash=topology_program_digest(program),
            selected_primary=selected_primary,
            steps=self.steps,
            expanded_messages=self.total_messages,
            warnings=self.warnings,
        )

    def _compile_repeat(
        self,
        statement: TopologyRepeatStatement,
        env: dict[str, int],
        path: str,
    ) -> None:
        if statement.var in env:
            raise TopologyProgramError(
                f"{path}: loop variable {statement.var!r} shadows an existing name"
            )
        values = self._range_values(statement.range, env, f"{path}.range")
        for value in values:
            self._tick(f"{path}.range")
            child_env = {**env, statement.var: value}
            for body_idx, step in enumerate(statement.body):
                self._compile_step(
                    step,
                    child_env,
                    f"{path}.body[{body_idx}]({statement.var}={value})",
                )

    def _compile_step(
        self,
        statement: TopologyStepStatement,
        env: dict[str, int],
        path: str,
    ) -> None:
        edges: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for edge_idx, template in enumerate(statement.edges):
            edge_path = f"{path}.edges[{edge_idx}]"
            for edge_env in self._iter_bindings(template.for_each, env, edge_path):
                self._tick(edge_path)
                if not self.evaluator.evaluate_bool(
                    template.when,
                    edge_env,
                    label=f"{edge_path}.when",
                ):
                    continue
                edge = (
                    self.evaluator.evaluate_int(
                        template.src,
                        edge_env,
                        label=f"{edge_path}.src",
                    ),
                    self.evaluator.evaluate_int(
                        template.dst,
                        edge_env,
                        label=f"{edge_path}.dst",
                    ),
                )
                if edge in seen:
                    self.warnings.append(f"{edge_path}: duplicate edge {edge} omitted")
                    continue
                seen.add(edge)
                edges.append(edge)
                if self.total_messages + len(edges) > self.limits.max_messages:
                    raise TopologyProgramError(
                        "topology program exceeds "
                        f"max_messages={self.limits.max_messages}"
                    )
        if not edges:
            self.warnings.append(
                f"{path}: empty step omitted; all nodes retain their prior state"
            )
            return
        if len(self.steps) >= self.limits.max_steps:
            raise TopologyProgramError(
                f"topology program exceeds max_steps={self.limits.max_steps}"
            )
        self.steps.append(
            CompiledTopologyStep(
                description=statement.description,
                operator_hint=statement.operator_hint,
                instruction=statement.instruction,
                edges=edges,
            )
        )
        self.total_messages += len(edges)

    def _iter_bindings(
        self,
        loops: list[TopologyLoopSpec],
        env: dict[str, int],
        path: str,
        index: int = 0,
    ) -> Iterator[dict[str, int]]:
        if index >= len(loops):
            yield env
            return
        loop = loops[index]
        if loop.var in env:
            raise TopologyProgramError(
                f"{path}: loop variable {loop.var!r} shadows an existing name"
            )
        values = self._range_values(
            loop.range,
            env,
            f"{path}.for_each[{index}].range",
        )
        for value in values:
            self._tick(f"{path}.for_each[{index}]")
            child_env = {**env, loop.var: value}
            yield from self._iter_bindings(
                loops,
                child_env,
                path,
                index + 1,
            )

    def _range_values(
        self,
        spec: TopologyRangeSpec,
        env: dict[str, int],
        label: str,
    ) -> range:
        start = self.evaluator.evaluate_int(spec.start, env, label=f"{label}.start")
        stop = self.evaluator.evaluate_int(spec.stop, env, label=f"{label}.stop")
        step = self.evaluator.evaluate_int(spec.step, env, label=f"{label}.step")
        if step == 0:
            raise TopologyProgramError(f"{label}: range step cannot be zero")
        values = range(start, stop, step)
        if len(values) > self.limits.max_loop_iterations:
            raise TopologyProgramError(
                f"{label}: loop has {len(values)} iterations; maximum is "
                f"{self.limits.max_loop_iterations}"
            )
        return values

    def _tick(self, label: str) -> None:
        self.expansion_operations += 1
        if self.expansion_operations > self.limits.max_expansion_operations:
            raise TopologyProgramError(
                f"{label}: expansion exceeds max_expansion_operations="
                f"{self.limits.max_expansion_operations}"
            )


class _ExpressionEvaluator:
    """Interpret the small integer expression language without executing code."""

    def __init__(self, limits: TopologyProgramLimits) -> None:
        self.limits = limits

    def evaluate_int(
        self,
        expression: ScalarExpression,
        env: dict[str, int],
        *,
        label: str,
    ) -> int:
        value = self._evaluate(expression, env, label)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TopologyProgramError(f"{label}: expression must produce an integer")
        return self._bounded_int(value, label)

    def evaluate_bool(
        self,
        expression: PredicateExpression,
        env: dict[str, int],
        *,
        label: str,
    ) -> bool:
        value = self._evaluate(expression, env, label)
        if not isinstance(value, bool):
            raise TopologyProgramError(f"{label}: predicate must produce a boolean")
        return value

    def _evaluate(
        self,
        expression: ScalarExpression | PredicateExpression,
        env: dict[str, int],
        label: str,
    ) -> int | bool:
        if isinstance(expression, bool):
            return expression
        if isinstance(expression, int):
            return self._bounded_int(expression, label)
        if not isinstance(expression, str):
            raise TopologyProgramError(f"{label}: unsupported expression type")
        source = expression.strip()
        if not source:
            raise TopologyProgramError(f"{label}: expression cannot be empty")
        if len(source) > self.limits.max_expression_length:
            raise TopologyProgramError(
                f"{label}: expression exceeds max_expression_length="
                f"{self.limits.max_expression_length}"
            )
        try:
            parsed = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            raise TopologyProgramError(f"{label}: invalid expression syntax") from exc
        if sum(1 for _ in ast.walk(parsed)) > self.limits.max_expression_nodes:
            raise TopologyProgramError(
                f"{label}: expression exceeds max_expression_nodes="
                f"{self.limits.max_expression_nodes}"
            )
        return self._eval_node(parsed.body, env, label)

    def _eval_node(
        self,
        node: ast.AST,
        env: dict[str, int],
        label: str,
    ) -> int | bool:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return node.value
            if isinstance(node.value, int):
                return self._bounded_int(node.value, label)
            raise TopologyProgramError(f"{label}: only integer constants are allowed")
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise TopologyProgramError(f"{label}: unknown name {node.id!r}")
            return self._bounded_int(env[node.id], label)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                value = self._require_bool(
                    self._eval_node(node.operand, env, label),
                    label,
                )
                return not value
            value = self._require_int(self._eval_node(node.operand, env, label), label)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return self._bounded_int(-value, label)
            if isinstance(node.op, ast.Invert):
                return self._bounded_int(~value, label)
            raise TopologyProgramError(f"{label}: unsupported unary operator")
        if isinstance(node, ast.BinOp):
            left = self._require_int(self._eval_node(node.left, env, label), label)
            right = self._require_int(self._eval_node(node.right, env, label), label)
            return self._binary(node.op, left, right, label)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(
                    self._require_bool(self._eval_node(item, env, label), label)
                    for item in node.values
                )
            if isinstance(node.op, ast.Or):
                return any(
                    self._require_bool(self._eval_node(item, env, label), label)
                    for item in node.values
                )
            raise TopologyProgramError(f"{label}: unsupported boolean operator")
        if isinstance(node, ast.Compare):
            left = self._require_int(self._eval_node(node.left, env, label), label)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._require_int(
                    self._eval_node(comparator, env, label),
                    label,
                )
                if not self._compare(operator, left, right, label):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            condition = self._require_bool(
                self._eval_node(node.test, env, label),
                label,
            )
            branch = node.body if condition else node.orelse
            return self._eval_node(branch, env, label)
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in _EXPRESSION_FUNCTIONS
                or node.keywords
            ):
                raise TopologyProgramError(f"{label}: function call is not allowed")
            args = [
                self._require_int(self._eval_node(arg, env, label), label)
                for arg in node.args
            ]
            return self._call(node.func.id, args, label)
        raise TopologyProgramError(
            f"{label}: expression node {type(node).__name__} is not allowed"
        )

    def _binary(
        self,
        operator: ast.operator,
        left: int,
        right: int,
        label: str,
    ) -> int:
        if isinstance(operator, ast.Add):
            value = left + right
        elif isinstance(operator, ast.Sub):
            value = left - right
        elif isinstance(operator, ast.Mult):
            value = left * right
        elif isinstance(operator, ast.FloorDiv):
            if right == 0:
                raise TopologyProgramError(f"{label}: division by zero")
            value = left // right
        elif isinstance(operator, ast.Mod):
            if right == 0:
                raise TopologyProgramError(f"{label}: modulo by zero")
            value = left % right
        elif isinstance(operator, ast.Pow):
            if right < 0 or right > 30:
                raise TopologyProgramError(f"{label}: exponent must be in [0, 30]")
            value = left**right
        elif isinstance(operator, ast.BitXor):
            value = left ^ right
        elif isinstance(operator, ast.BitAnd):
            value = left & right
        elif isinstance(operator, ast.BitOr):
            value = left | right
        elif isinstance(operator, ast.LShift):
            if right < 0 or right > 30:
                raise TopologyProgramError(f"{label}: shift must be in [0, 30]")
            value = left << right
        elif isinstance(operator, ast.RShift):
            if right < 0 or right > 30:
                raise TopologyProgramError(f"{label}: shift must be in [0, 30]")
            value = left >> right
        else:
            raise TopologyProgramError(f"{label}: unsupported binary operator")
        return self._bounded_int(value, label)

    def _compare(
        self,
        operator: ast.cmpop,
        left: int,
        right: int,
        label: str,
    ) -> bool:
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.NotEq):
            return left != right
        if isinstance(operator, ast.Lt):
            return left < right
        if isinstance(operator, ast.LtE):
            return left <= right
        if isinstance(operator, ast.Gt):
            return left > right
        if isinstance(operator, ast.GtE):
            return left >= right
        raise TopologyProgramError(f"{label}: unsupported comparison operator")

    def _call(self, name: str, args: list[int], label: str) -> int:
        if name == "abs" and len(args) == 1:
            value = abs(args[0])
        elif name == "min" and args:
            value = min(args)
        elif name == "max" and args:
            value = max(args)
        elif name == "ceil_log2" and len(args) == 1 and args[0] > 0:
            value = (args[0] - 1).bit_length()
        elif name == "floor_log2" and len(args) == 1 and args[0] > 0:
            value = args[0].bit_length() - 1
        elif name == "pow2" and len(args) == 1 and 0 <= args[0] <= 30:
            value = 1 << args[0]
        else:
            raise TopologyProgramError(
                f"{label}: invalid arguments for function {name}"
            )
        return self._bounded_int(value, label)

    def _bounded_int(self, value: int, label: str) -> int:
        if abs(value) > self.limits.max_abs_integer:
            raise TopologyProgramError(
                f"{label}: integer magnitude exceeds {self.limits.max_abs_integer}"
            )
        return value

    @staticmethod
    def _require_int(value: int | bool, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TopologyProgramError(f"{label}: integer operand required")
        return value

    @staticmethod
    def _require_bool(value: int | bool, label: str) -> bool:
        if not isinstance(value, bool):
            raise TopologyProgramError(f"{label}: boolean operand required")
        return value
