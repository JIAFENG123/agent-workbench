from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.rag.retriever import retrieve
from app.tools.registry import Tool, ToolContext, ToolResult, registry

MAX_EXPONENT = 64


class KbSearchArgs(BaseModel):
    query: str = Field(
        description=("要在知识库中检索的问题或关键词，尽量保留原文中的专有名词与政策术语。")
    )
    top_k: int = Field(default=6, ge=1, le=20, description="返回的片段数量。")


class CurrentTimeArgs(BaseModel):
    timezone: str = Field(default="Asia/Shanghai", description="IANA 时区名，例如 Asia/Shanghai。")


class CalculatorArgs(BaseModel):
    expression: str = Field(description="四则运算表达式，支持 + - * / // % ** 与括号。")


async def kb_search(context: ToolContext, args: KbSearchArgs) -> ToolResult:
    result = await retrieve(
        context.session,
        tenant_id=context.tenant_id,
        query=args.query,
        final_k=args.top_k,
    )
    if result.empty:
        return ToolResult.success(
            "知识库中没有检索到与该问题相关的内容。",
            citations=[],
            stage_ms=result.stage_ms,
        )

    blocks = [
        f"[{citation.index}] 来源：{citation.filename}（第 {citation.ordinal + 1} 段）\n"
        f"{citation.snippet}"
        for citation in result.citations
    ]
    return ToolResult.success(
        "\n\n".join(blocks),
        citations=[
            {
                "index": citation.index,
                "filename": citation.filename,
                "document_id": str(citation.document_id),
                "chunk_id": str(citation.chunk_id),
                "ordinal": citation.ordinal,
                "score": citation.score,
            }
            for citation in result.citations
        ],
        queries_used=result.queries_used,
        reranked=result.reranked,
        stage_ms=result.stage_ms,
    )


async def current_time(_: ToolContext, args: CurrentTimeArgs) -> ToolResult:
    try:
        zone = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ToolResult.failure(f"未知时区：{args.timezone}")
    now = datetime.now(zone)
    return ToolResult.success(
        f"{now.isoformat()}（{args.timezone}）",
        timezone=args.timezone,
        iso=now.isoformat(),
    )


_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _evaluate(node: ast.AST) -> float:
    """Evaluate an arithmetic AST without ever calling eval() on user input."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("只支持数字字面量")
        return float(node.value)
    if isinstance(node, ast.BinOp):
        operator_fn = _BIN_OPS.get(type(node.op))
        if operator_fn is None:
            raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
        left, right = _evaluate(node.left), _evaluate(node.right)
        if operator_fn is operator.pow and abs(right) > MAX_EXPONENT:
            raise ValueError(f"指数过大（上限 {MAX_EXPONENT}）")
        return operator_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        unary_fn = _UNARY_OPS.get(type(node.op))
        if unary_fn is None:
            raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
        return unary_fn(_evaluate(node.operand))
    raise ValueError(f"表达式包含不允许的语法：{type(node).__name__}")


async def calculator(_: ToolContext, args: CalculatorArgs) -> ToolResult:
    try:
        tree = ast.parse(args.expression, mode="eval")
    except SyntaxError:
        return ToolResult.failure(f"表达式语法错误：{args.expression}")
    try:
        value = _evaluate(tree.body)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        return ToolResult.failure(f"计算失败：{exc}")
    formatted = int(value) if value.is_integer() else value
    return ToolResult.success(f"{args.expression} = {formatted}", value=formatted)


def register_builtin_tools() -> None:
    registry.register(
        Tool(
            name="kb_search",
            description=(
                "检索租户知识库。适用于所有需要事实依据的问题（平台规则、政策条款、商品资料）。"
                "返回带编号的片段，回答时必须用 [编号] 标注引用来源。"
            ),
            args_model=KbSearchArgs,
            handler=kb_search,
        )
    )
    registry.register(
        Tool(
            name="current_time",
            description="获取指定时区的当前时间，用于涉及时效性的判断（如政策生效日期）。",
            args_model=CurrentTimeArgs,
            handler=current_time,
        )
    )
    registry.register(
        Tool(
            name="calculator",
            description="执行精确的算术运算。涉及数字计算时使用，不要心算。",
            args_model=CalculatorArgs,
            handler=calculator,
        )
    )


ToolName = Literal["kb_search", "current_time", "calculator"]
