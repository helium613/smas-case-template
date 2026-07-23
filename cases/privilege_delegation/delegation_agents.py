"""④実行主体層: IAM委任チェーン(AssumeRole型)専用エージェント(ケース5固有)。

liquid_democracyのDelegatingAgentと同様、trust宣言は外部(シナリオ設定)から
固定で与える——「誰を信頼するか(delegate_to)」の1種類の固定ルールエージェントで
足りる(liquid_democracyのDirectVotingAgent/DelegatingAgentのような行動の分岐が
不要: 「trustを与えるか与えないか」はdelegate_to=Noneかどうかで表現できる)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class TrustDeclaringAgent:
    """毎ラウンド、固定のtrust宣言(delegate_to)をそのまま繰り返す。

    delegate_to=None は「誰にも自分をassumeさせない」ことを意味する。
    """

    def __init__(self, agent_id: str, delegate_to: str | None) -> None:
        self.agent_id = agent_id
        self.delegate_to = delegate_to

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="trust", delegate_to=self.delegate_to, reasoning=None)
