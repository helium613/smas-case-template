"""ケース5(IAM委任チェーンの権限昇格)の意思決定支援ツール群。

①〜⑤の実行パイプラインには含まれない、事後の分析・監査用ユーティリティ
(verification_kit/と同じ「実行パイプラインの外側」の位置づけだが、このケース
固有の分析のため verification_kit/ ではなく cases/privilege_delegation/ 側に置く)。

「権限昇格ゼロ」自体は目標にならない(intended_max_tierが一部の多段到達を
意図的に許容しているため)。この分析群は、実際に運用する側が3つの場面で使う
ことを想定する:

1. **chokepointランキング(本ファイル、第一弾)**: 事後分析。既に発生した(または
   発生しうる)権限昇格に対し、どのtrust宣言を1件取り除けば最も効果的に解消
   できるかをランキングする——「根本原因の特定」(D-60のシーン3、注入した1件を
   除く)を、任意のtrust設定に一般化したもの。限られた対応リソースをどこに
   割くべきかの優先順位づけに使う。
2. **What-if事前チェック(次の一手)**: 新しいtrust宣言を追加する"前"に、それが
   昇格を生むかを判定する予防的ゲート。
3. **blast radius計算(次の一手)**: 特定のロールが侵害された場合に、現在の
   trust設定でどこまで到達しうるかを計算する、インシデント対応用の即時計算。
"""
from __future__ import annotations

from dataclasses import dataclass

from schemas.incentive_schema import Declaration

from incentive_engine import PrivilegeDelegationEngine


@dataclass
class ChokepointResult:
    """1件のtrust宣言(edge)を取り除いた場合の効果。"""

    truster_agent_id: str
    """このエージェントがtrustを与えている(delegate_toの宣言元)。"""

    trusted_agent_id: str
    """信頼されている相手(truster_agent_idをassumeできる側)。"""

    escalations_resolved: int
    """このedgeを取り除くと、権限昇格状態から解消されるエージェントの数。"""

    resolved_agent_ids: list[str]
    """このedgeを取り除くと権限昇格状態から解消されるエージェントのID一覧。"""

    excess_tier_reduced: int
    """このedgeを取り除くと減少する、意図された上限からの超過tierの合計。
    escalations_resolvedが同数の場合の指標として使う(超過幅が大きい昇格を
    解消するedgeほど優先度が高い、という判断に使える)。"""


def _total_excess(reachable: dict[str, int], intended_max_tier: dict[str, int]) -> int:
    return sum(max(0, tier - intended_max_tier[agent_id]) for agent_id, tier in reachable.items())


def _escalated_agents(reachable: dict[str, int], intended_max_tier: dict[str, int]) -> set[str]:
    return {agent_id for agent_id, tier in reachable.items() if tier > intended_max_tier[agent_id]}


def rank_chokepoint_edges(
    engine: PrivilegeDelegationEngine, declarations: list[Declaration]
) -> list[ChokepointResult]:
    """各trust宣言(edge)を1件ずつ取り除いた場合に、権限昇格がどれだけ解消するかを
    ランキングする(excess_tier_reduced降順、次点でescalations_resolved降順)。

    delegate_to=Noneの宣言(trustを与えていない)は対象外。計測のみ(メカニズムの
    構成要素にしない、CLAUDE.md 9章と同じ思想)——実際にtrust宣言を書き換えたり
    環境に書き込んだりはしない。
    """
    baseline_reachable = engine.resolve_reachable_tiers(declarations)
    baseline_escalated = _escalated_agents(baseline_reachable, engine.parameters.intended_max_tier)
    baseline_excess = _total_excess(baseline_reachable, engine.parameters.intended_max_tier)

    results: list[ChokepointResult] = []
    for d in declarations:
        if d.delegate_to is None:
            continue
        modified = [
            Declaration(
                agent_id=decl.agent_id,
                delegate_to=(None if decl.agent_id == d.agent_id else decl.delegate_to),
            )
            for decl in declarations
        ]
        reachable_without = engine.resolve_reachable_tiers(modified)
        escalated_without = _escalated_agents(reachable_without, engine.parameters.intended_max_tier)
        excess_without = _total_excess(reachable_without, engine.parameters.intended_max_tier)

        resolved_agents = sorted(baseline_escalated - escalated_without)
        results.append(
            ChokepointResult(
                truster_agent_id=d.agent_id,
                trusted_agent_id=d.delegate_to,
                escalations_resolved=len(resolved_agents),
                resolved_agent_ids=resolved_agents,
                excess_tier_reduced=baseline_excess - excess_without,
            )
        )

    results.sort(key=lambda r: (r.excess_tier_reduced, r.escalations_resolved), reverse=True)
    return results
