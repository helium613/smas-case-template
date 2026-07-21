"""④実行主体層: LLM実物(Anthropic API、Tool Use/JSON Schema、優先度3)。

目玉シーンのみ数回の呼び出しに限定する(execution_layer_priority.md)。
大量試行には agents/llm_mock.py を使うこと。

自然言語のみのやり取りに依存する実装は禁止(CLAUDE.md 6章)。必ずTool Use/
JSON Schemaで構造化出力を強制する。anthropic SDK は decide() 実行時に遅延
importする(テンプレート/モック運用時にAPIキーが無くてもimportエラーに
ならないようにするため)。
"""
from __future__ import annotations

import json
import os

from schemas.agent_schema import ActionOutput, ObservationInput

_DECLARE_BID_TOOL = {
    "name": "declare_bid",
    "description": "このラウンドでの申告値を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["bid", "abstain"]},
            "declared_value": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": ["action", "declared_value"],
    },
}


class AnthropicToolUseAgent:
    def __init__(self, agent_id: str, true_value: float, model: str = "claude-sonnet-5") -> None:
        self.agent_id = agent_id
        self.true_value = true_value
        self.model = model

    def decide(self, observation: ObservationInput) -> ActionOutput:
        import anthropic  # 遅延import

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model=self.model,
            max_tokens=512,
            tools=[_DECLARE_BID_TOOL],
            tool_choice={"type": "tool", "name": "declare_bid"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "あなたはタスク配分メカニズムに参加するエージェントです。"
                        f"あなたにとっての真の評価額は {self.true_value} です。"
                        f"環境の要約: {json.dumps(observation.trace_summary, ensure_ascii=False)}\n"
                        "declare_bid ツールで申告してください。"
                    ),
                }
            ],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "declare_bid":
                data = block.input
                return ActionOutput(
                    action=data["action"],
                    declared_value=float(data["declared_value"]),
                    reasoning=data.get("reasoning"),
                )
        raise RuntimeError("LLM がツール呼び出しを返しませんでした")
