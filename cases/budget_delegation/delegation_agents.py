"""④実行主体層: 予算委任チェーン専用エージェント(ケース6固有)。

privilege_delegationのTrustDeclaringAgentと同様、委任宣言は外部(シナリオ設定)
から固定で与える——「誰にいくら委任するか(delegate_to, declared_value)」の
1種類の固定ルールエージェントで足りる。このケースの主眼は虚偽申告ではなく、
個別に正当な委任判断の合成が生む望ましくない結果であり、逸脱エージェントの
種類分けは不要(#11参照、privilege_delegationと同型の理由)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class BudgetDelegatingAgent:
    """毎ラウンド、固定の委任宣言(delegate_to, declared_value)をそのまま繰り返す。

    delegate_to=None は「誰にも委任しない(自分の保有額をそのまま保持する)」
    ことを意味する。
    """

    def __init__(self, agent_id: str, delegate_to: str | None, declared_value: float = 0.0) -> None:
        self.agent_id = agent_id
        self.delegate_to = delegate_to
        self.declared_value = declared_value

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(
            action="delegate_budget",
            delegate_to=self.delegate_to,
            declared_value=self.declared_value,
            reasoning=None,
        )
