"""④実行主体層: 投票ドメイン専用エージェント(ケース3固有)。

真の評価額から降順ランキングを申告する正直エージェントと、ボルダ得点特有の
「埋葬(burying)」戦術を行う戦術的エージェント。いずれも他エージェントの
申告内容を一切知らずに実行できる固定ルール(agents/rule_based.pyの
GreedyOverstatingAgent等と同じ設計方針、agent_layer_variations.md)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class HonestVotingAgent:
    """真の評価額の降順どおりに、候補への順位を正直に申告する。"""

    def __init__(self, agent_id: str, true_values: dict[str, float]) -> None:
        self.agent_id = agent_id
        self.true_values = true_values

    def true_ranking(self) -> list[str]:
        return sorted(self.true_values, key=lambda c: self.true_values[c], reverse=True)

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="rank", declared_ranking=self.true_ranking(), reasoning=None)


class BuryingStrategicAgent:
    """ボルダ得点の「埋葬」戦術: 真の2位候補を最下位まで落として申告する。

    真の1位はそのまま1位に残し、真の2位(=最有力の対抗馬になりがちな候補)
    だけを最下位に落とす、という単純な固定ルール。他エージェントの申告や
    集計結果を一切参照しない(4シーン先読み等の高度な戦略は使わない)。

    ボルダ得点は非耐戦略性メカニズムのため、候補者数・他エージェントの選好
    次第でこの単純な戦術だけで得をする場合があるが、常に得をするとは限らず、
    構成によっては無意味・逆効果になる(「耐戦略性の欠如を示す一例」であり、
    「必勝法」ではない、mechanism_catalog.md ファミリー2)。
    """

    def __init__(self, agent_id: str, true_values: dict[str, float]) -> None:
        self.agent_id = agent_id
        self.true_values = true_values

    def manipulated_ranking(self) -> list[str]:
        true_ranking = sorted(self.true_values, key=lambda c: self.true_values[c], reverse=True)
        if len(true_ranking) < 3:
            return true_ranking
        first, second, *rest = true_ranking
        return [first, *rest, second]

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="rank", declared_ranking=self.manipulated_ranking(), reasoning=None)
