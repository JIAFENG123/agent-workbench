from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.tools.builtin import CalculatorArgs, calculator
from app.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult

# The calculator never touches the context, so a stand-in keeps these tests free of a
# database session.
NO_CONTEXT = None  # type: ignore[assignment]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1+2", "3"),
        ("2**10", "1024"),
        ("10/4", "2.5"),
        ("(3+5)*2", "16"),
        ("-3 + 1", "-2"),
        ("7 % 3", "1"),
        ("7 // 2", "3"),
    ],
)
async def test_calculator_evaluates_arithmetic(expression: str, expected: str) -> None:
    result = await calculator(NO_CONTEXT, CalculatorArgs(expression=expression))
    assert result.ok
    assert result.meta["value"] == pytest.approx(float(expected))
    assert expected in result.content


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('whoami')",
        "open('/etc/passwd').read()",
        "a + 1",
        "[1, 2, 3]",
        "lambda: 1",
        "(1).__class__",
    ],
)
async def test_calculator_rejects_non_arithmetic_expressions(expression: str) -> None:
    result = await calculator(NO_CONTEXT, CalculatorArgs(expression=expression))
    assert not result.ok


@pytest.mark.parametrize("expression", ["2 ** 1000", "2 ** 65"])
async def test_calculator_caps_exponents(expression: str) -> None:
    """A large exponent would pin the CPU on a 0.1-core instance."""
    result = await calculator(NO_CONTEXT, CalculatorArgs(expression=expression))
    assert not result.ok
    assert "指数过大" in result.content


@pytest.mark.parametrize("expression", ["1/0", "1 % 0"])
async def test_calculator_handles_division_by_zero(expression: str) -> None:
    result = await calculator(NO_CONTEXT, CalculatorArgs(expression=expression))
    assert not result.ok


class _EchoArgs(BaseModel):
    message: str
    repeat: int = 1


async def _echo(_: ToolContext, args: _EchoArgs) -> ToolResult:
    return ToolResult.success(args.message * args.repeat)


def _make_tool(**overrides: object) -> Tool:
    defaults: dict[str, object] = {
        "name": "echo",
        "description": "echo back",
        "args_model": _EchoArgs,
        "handler": _echo,
    }
    defaults.update(overrides)
    return Tool(**defaults)  # type: ignore[arg-type]


async def test_tool_invokes_handler_with_validated_arguments() -> None:
    tool = _make_tool()
    result = await tool.invoke(NO_CONTEXT, {"message": "ab", "repeat": 3})
    assert result.ok
    assert result.content == "ababab"


async def test_tool_rejects_invalid_arguments_without_raising() -> None:
    tool = _make_tool()
    result = await tool.invoke(NO_CONTEXT, {"repeat": 2})
    assert not result.ok
    assert "参数校验失败" in result.content


async def test_tool_treats_missing_arguments_as_empty() -> None:
    tool = _make_tool()
    result = await tool.invoke(NO_CONTEXT, {})
    assert not result.ok


async def test_tool_spec_exposes_a_json_schema() -> None:
    spec = _make_tool().spec()
    assert spec.name == "echo"
    assert set(spec.parameters["properties"]) == {"message", "repeat"}
    assert spec.to_openai()["type"] == "function"


async def test_tool_survives_a_handler_that_raises() -> None:
    async def _broken(_: ToolContext, __: _EchoArgs) -> ToolResult:
        raise RuntimeError("upstream exploded")

    tool = _make_tool(handler=_broken)
    result = await tool.invoke(NO_CONTEXT, {"message": "x"})
    assert not result.ok
    assert "upstream exploded" in result.content


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_make_tool())


def test_registry_allowlist_hides_unauthorised_tools() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool(name="alpha"))
    registry.register(_make_tool(name="beta"))

    assert registry.names() == ["alpha", "beta"]
    assert [spec.name for spec in registry.specs()] == ["alpha", "beta"]
    assert [spec.name for spec in registry.specs(["beta"])] == ["beta"]
    assert registry.specs(["does-not-exist"]) == []
    assert registry.get("missing") is None
