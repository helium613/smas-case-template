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


class FanOutTrustDeclaringAgent:
    """毎ラウンド、複数の固定trust宣言を同時に繰り返す(ファンアウト、D-80)。

    1つの`Declaration`は引き続き1つのdelegate_toしか持てない(A側は無変更)。
    ファンアウトは、同じagent_idを持つ複数の`Declaration`をラウンドごとに
    まとめて提出することで表現する——`PrivilegeDelegationEngine`のBFS実装
    (`by_delegate_to.setdefault(d.delegate_to, []).append(d.agent_id)`)は
    Declarationを1件ずつ独立に処理するため、同じagent_idの複数件が混在しても
    無改造で正しく動く(実測で確認済み、D-80)。

    `decide()`はAgentプロトコル互換のため最初の宛先だけを返す(単一宛先しか
    知らない呼び出し元との後方互換)。実際に複数宛先を集めるには`decide_all()`
    を呼ぶ(deviation_test.pyの`_collect_declarations`が対応済み)。
    """

    def __init__(self, agent_id: str, delegate_to_targets: list[str]) -> None:
        self.agent_id = agent_id
        self.delegate_to_targets = delegate_to_targets

    def decide(self, observation: ObservationInput) -> ActionOutput:
        first = self.delegate_to_targets[0] if self.delegate_to_targets else None
        return ActionOutput(action="trust", delegate_to=first, reasoning=None)

    def decide_all(self, observation: ObservationInput) -> list[ActionOutput]:
        if not self.delegate_to_targets:
            return [ActionOutput(action="trust", delegate_to=None, reasoning=None)]
        return [
            ActionOutput(action="trust", delegate_to=target, reasoning=None)
            for target in self.delegate_to_targets
        ]
