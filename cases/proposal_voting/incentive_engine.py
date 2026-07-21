"""②誘因構造層 B側: ボルダ得点による投票メカニズム(mechanism_catalog.md ファミリー2)。

支払いなし・順位申告の集約という、ケース1(VCG、支払いあり・1回性)・ケース2
(トリガー戦略、支払いなし・繰り返しゲーム)のいずれとも異なる性質の実証(D-27)。

ボルダ得点は同カタログのファミリー2表で「戦術的な順位操作が可能」と明記された
非耐戦略性メカニズムであり、これをそのまま使うことで、⑤検証層・③モンテカルロが
「耐戦略性を満たさない設計」を正しく検出できるかを確認する狙いを持つ
(mechanism_catalog.md Part3、ケース1・2は逆に「良い設計」の検証実績しかなかった)。
"""
from __future__ import annotations

from pydantic import BaseModel

from aggregation import aggregate_by_ranking
from schemas.incentive_schema import AllocationResult, Declaration


class BordaVotingParameters(BaseModel):
    """候補(採用する提案)の一覧。全エージェントの申告ランキングはこの並びの順列。"""

    candidate_ids: list[str]


class BordaVotingEngine:
    """全員が候補への順位を申告し、ボルダ得点最多の候補が採用される(支払いなし)。

    ③集約層の共通実装 aggregation.aggregate_by_ranking(pref_voting利用)を
    そのまま呼ぶ。②誘因構造層固有の仕事は「投票結果=配分結果」への変換のみ。
    """

    def __init__(self, parameters: BordaVotingParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        rankings = [d.declared_ranking for d in declarations]
        if any(ranking is None for ranking in rankings):
            raise ValueError(
                "BordaVotingEngineはdeclared_rankingが必須(declared_valueは使わない)"
            )
        winner = aggregate_by_ranking(self.parameters.candidate_ids, rankings)
        return AllocationResult(allocated_agent_ids=[winner], payments={})
