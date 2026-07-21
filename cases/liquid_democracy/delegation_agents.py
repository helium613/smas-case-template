"""④実行主体層: 委任ドメイン専用エージェント(ケース4固有)。

直接投票する固定ルールエージェントと、指定した委任先にそのまま委任する固定ルール
エージェント。委任先は外部(シナリオ設定)から与える——委任が「忠実」(自分の
真の選好を共有する相手への委任)か「循環」かは、シナリオ側がどう配線するかで
決まり、エージェント自身のロジックは同じ(agents/rule_based.pyと同じ設計方針、
固定的な条件分岐で予測可能に動く)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class DirectVotingAgent:
    """委任せず、自分の真の選好どおりに直接投票する。"""

    def __init__(self, agent_id: str, true_preference: str) -> None:
        self.agent_id = agent_id
        self.true_preference = true_preference

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="vote", declared_ranking=[self.true_preference], reasoning=None)


class DelegatingAgent:
    """自分では投票せず、指定した委任先にそのまま委任する。"""

    def __init__(self, agent_id: str, delegate_to: str) -> None:
        self.agent_id = agent_id
        self.delegate_to = delegate_to

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="delegate", delegate_to=self.delegate_to, reasoning=None)
