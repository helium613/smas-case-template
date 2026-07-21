"""④実行主体層: LLM実物(Anthropic API、Tool Use/JSON Schema、優先度3)。

目玉シーンのみ数回の呼び出しに限定する(execution_layer_priority.md)。
大量試行には agents/llm_mock.py を使うこと。

自然言語のみのやり取りに依存する実装は禁止(CLAUDE.md 6章)。必ずTool Use/
JSON Schemaで構造化出力を強制する。anthropic SDK は decide() 実行時に遅延
importする(テンプレート/モック運用時に`anthropic`未インストール・APIキーが
無くてもimportエラーにならないようにするため)。
"""
from __future__ import annotations

import json

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


def missing_credentials_reason() -> str | None:
    """`anthropic`が呼び出せる状態かを確認する。呼び出せなければ理由文字列を返す
    (呼び出せる場合はNone)。目玉シーンのデモスクリプト側で、CI・鍵未設定環境
    でも例外で落ちずに「スキップ」できるようにするための、事前チェック用。

    `anthropic.Anthropic()`(引数なし)は、環境変数(ANTHROPIC_API_KEY /
    ANTHROPIC_AUTH_TOKEN)だけでなく`ant auth login`のプロファイルからも
    資格情報を解決する(claude-api skill参照)。そのため`os.environ`を直接見る
    のではなく、実際にクライアントを構築してみて判定する。
    """
    try:
        import anthropic
    except ImportError:
        return "anthropicパッケージが未インストールです(pip install anthropic)"

    try:
        anthropic.Anthropic()
    except anthropic.AnthropicError as exc:
        return f"資格情報が解決できません: {exc}"
    return None


class AnthropicToolUseAgent:
    """LLM実物(Tool Use強制)によるエージェント。デフォルトモデルはclaude-opus-4-8
    (claude-api skillの既定方針: ユーザーが明示的に別モデルを指定しない限りopus-4-8)。
    目玉シーンでの数回の呼び出しに限定するため、ここでコスト最適化は行わない。
    """

    def __init__(self, agent_id: str, true_value: float, model: str = "claude-opus-4-8") -> None:
        self.agent_id = agent_id
        self.true_value = true_value
        self.model = model

    def decide(self, observation: ObservationInput) -> ActionOutput:
        import anthropic  # 遅延import

        client = anthropic.Anthropic()
        try:
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
        except anthropic.AuthenticationError as exc:
            raise RuntimeError(f"LLM実物エージェント({self.agent_id}): 認証エラー") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(f"LLM実物エージェント({self.agent_id}): レート制限") from exc
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"LLM実物エージェント({self.agent_id}): APIエラー({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"LLM実物エージェント({self.agent_id}): 接続エラー") from exc

        for block in response.content:
            if block.type == "tool_use" and block.name == "declare_bid":
                data = block.input
                return ActionOutput(
                    action=data["action"],
                    declared_value=float(data["declared_value"]),
                    reasoning=data.get("reasoning"),
                )
        raise RuntimeError(f"LLM実物エージェント({self.agent_id}): ツール呼び出しを返しませんでした")
