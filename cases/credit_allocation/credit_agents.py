"""④実行主体層: 信用枠配分ケース固有のエージェント。

ルールベースの基準点(execution_layer_priority.md 優先度1)。「正直」の定義が
ケース1(真の評価額をそのまま申告)と異なり、ここでは「信用枠を超えない範囲で
真の評価額を申告する」こと(=遵守)を指す。逸脱エージェントは既存の共通実装
agents.rule_based.GreedyOverstatingAgent をそのまま再利用できる(信用枠を無視して
常に固定高値を宣言する、という振る舞いがそのまま「常に違反する」に対応するため、
ケース2向けの新規実装は不要——④実行主体層のプラガブル性の実例、evaluation_criteria.md #11)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class CreditAwareHonestAgent:
    """真の評価額がラウンドごとに変動しつつ、常に自分の信用枠(observationから取得)
    を超えない範囲で申告する(=遵守を続ける基準点)。

    信用枠は observation.trace_summary["credit_limit"] から取得する(deviation_test.py
    が申告収集前に compute_credit_limit で計算し、observationへ載せる)。信用枠情報が
    無い場合は真の評価額をそのまま申告する(初回ラウンド等、フォールバック)。
    """

    def __init__(
        self,
        agent_id: str,
        agent_index: int,
        n_agents: int,
        high_value: float = 15.0,
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
        true_value = self.true_value_for_round(round_id)
        credit_limit = observation.trace_summary.get("credit_limit")
        declared_value = true_value if credit_limit is None else min(true_value, credit_limit)
        return ActionOutput(action="bid", declared_value=declared_value, reasoning=None)


class CreditLimitMaximizingAgent:
    """信用枠のすぐ下を狙って恒常的に申告する固定ルール(D-37のRed Team LLMが発見した
    戦略を、決定論的なルールベースとして再現したもの)。真の評価額を一切参照せず、
    常に自分の信用枠(observation.trace_summary["credit_limit"])をそのまま申告する。

    信用枠は真の評価額と無関係に過去の遵守実績のみから育つため、この戦略は
    「遵守」(信用枠以内)でありながら恒常的な過大申告になりうる——TriggerStrategyEngine
    は信用枠以内かどうかしかチェックしないため、一度も検出されない(D-37)。
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def decide(self, observation: ObservationInput) -> ActionOutput:
        credit_limit = observation.trace_summary.get("credit_limit")
        declared_value = credit_limit if credit_limit is not None else 0.0
        return ActionOutput(action="bid", declared_value=declared_value, reasoning=None)
