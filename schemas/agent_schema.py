"""④実行主体層 A側: 型定義のみ。

プラガブル性は「型の互換性」のみを意味する。「振る舞いの同等性」
(LLMが理論通りに動くこと)は保証されない(CLAUDE.md 2章 原則4、
agent_layer_variations.md)。
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel


class ObservationInput(BaseModel):
    """①環境層の痕跡から取得できる情報。

    共通最小限データ(trace_summary)+ 実装固有の追加コンテキスト(オプショナル)、
    という2段構造(agent_layer_variations.md)。
    """

    trace_summary: dict
    extended_context: Optional[str] = None  # LLM向け: テキスト化された文脈
    belief_state: Optional[dict] = None  # POMDP向け: 独自の内部表現


class ActionOutput(BaseModel):
    """JSON Schemaで構造化された行動。自然言語のみのやり取りに依存する実装は禁止
    (CLAUDE.md 6章)。reasoning は人間可読用で、システムロジックはこれに依存しない。

    declared_value・declared_ranking・delegate_to は schemas/incentive_schema.py の
    Declaration と同じ理由(ケース3で順位申告、ケース4で委任メカニズムに対応、
    CLAUDE.md 11章)で並行して追加した排他的フィールド。
    """

    action: str
    declared_value: float = 0.0
    declared_ranking: Optional[list[str]] = None
    delegate_to: Optional[str] = None
    reasoning: Optional[str] = None


@runtime_checkable
class Agent(Protocol):
    """④実行主体層の共通インターフェース。ルールベース/LLMモック/LLM実物いずれも
    このプロトコルを満たす(agent_layer_variations.md「前提: 共通インターフェース」)。
    """

    agent_id: str

    def decide(self, observation: ObservationInput) -> ActionOutput: ...
