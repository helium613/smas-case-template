"""④実行主体層: ルールベースエージェント(基準点、優先度1・必須)。

固定的な条件分岐で、予測可能に動く。①〜⑤層のバグと"エージェントの気まぐれ"を
切り分けるための基準点として機能する(execution_layer_priority.md)。
このファイルはそのまま使う、または微修正で使う雛形(repository_structure.md)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class HonestRuleBasedAgent:
    """常に真の評価額を正直に申告する(シーン1: 平常時に使う)。"""

    def __init__(self, agent_id: str, true_value: float) -> None:
        self.agent_id = agent_id
        self.true_value = true_value

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="bid", declared_value=self.true_value, reasoning=None)


class OverstatingRuleBasedAgent:
    """真の評価額を factor 倍で過大申告する固定ルール(シーン2: 逸脱注入に使う)。"""

    def __init__(self, agent_id: str, true_value: float, factor: float = 1.3) -> None:
        self.agent_id = agent_id
        self.true_value = true_value
        self.factor = factor

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(
            action="bid", declared_value=self.true_value * self.factor, reasoning=None
        )


class FluctuatingHonestAgent:
    """真の評価額がラウンドごとに交代する、正直申告エージェント。

    実際のタスク配分では同じ主体でも案件ごとに評価額が変わりうるため、固定値の
    HonestRuleBasedAgentより現実的な基準点として使う。observation.trace_summary
    の "round" を見て、あらかじめ決めた周期(round % n_agents == agent_index)で
    自分が「今回の高評価者」かどうかを機械的に切り替える。乱数を使わないため、
    シーン1(平常時)の当選が主体間でどう分配されるかを決定論的・再現可能に
    保てる(シーン3の判定基準を検証しやすくするための、疎通確認向けの単純化)。
    """

    def __init__(
        self,
        agent_id: str,
        agent_index: int,
        n_agents: int,
        high_value: float = 12.0,
        low_value: float = 8.0,
    ) -> None:
        self.agent_id = agent_id
        self.agent_index = agent_index
        self.n_agents = n_agents
        self.high_value = high_value
        self.low_value = low_value

    def true_value_for_round(self, round_id: int) -> float:
        return self.high_value if round_id % self.n_agents == self.agent_index else self.low_value

    def decide(self, observation: ObservationInput) -> ActionOutput:
        round_id = observation.trace_summary.get("round", 0)
        return ActionOutput(
            action="bid", declared_value=self.true_value_for_round(round_id), reasoning=None
        )


class GreedyOverstatingAgent:
    """真の評価額に関わらず、常に固定の高値を宣言する(強い過大申告の例)。

    シーン2(逸脱注入)で当選を独占させ、シーン3(自己拘束の確認)で
    「当選はできても、支払い超過により正直申告時より効用が下がる」ことを
    反実仮想比較で示すために使う(DECISIONS.md D-07)。経済合理性を無視した
    独占の継続(公平性#10・適応的逸脱#12の対象)への対処は、信用ゲートともども
    2ケース目に移設(engine/incentive_engine.py のプレビュー節参照)。
    """

    def __init__(self, agent_id: str, fixed_declared_value: float = 1000.0) -> None:
        self.agent_id = agent_id
        self.fixed_declared_value = fixed_declared_value

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="bid", declared_value=self.fixed_declared_value, reasoning=None)
