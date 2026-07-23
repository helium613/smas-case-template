"""ケース5(IAM委任チェーンの権限昇格)の意思決定支援ツール群。

①〜⑤の実行パイプラインには含まれない、事後の分析・監査用ユーティリティ
(verification_kit/と同じ「実行パイプラインの外側」の位置づけだが、このケース
固有の分析のため verification_kit/ ではなく cases/privilege_delegation/ 側に置く)。

「権限昇格ゼロ」自体は目標にならない(intended_max_tierが一部の多段到達を
意図的に許容しているため)。この分析群は、実際に運用する側が3つの場面で使う
ことを想定する:

1. **chokepointランキング**: 事後分析。既に発生した(または発生しうる)権限昇格に
   対し、どのtrust宣言を1件取り除けば最も効果的に解消できるかをランキングする
   ——「根本原因の特定」(D-60のシーン3、注入した1件を除く)を、任意のtrust設定に
   一般化したもの。限られた対応リソースをどこに割くべきかの優先順位づけに使う。
2. **候補trust宣言の総当たりスキャン(本ファイル、第二弾)**: 事前チェック。
   まだ存在しない新規trust宣言の候補を全て総当たりし、追加した場合に権限昇格を
   新たに生む(または悪化させる)ものはどれかを一括で判定する。chokepointランキング
   の逆方向(事後の原因特定ではなく、事前に危険な追加を洗い出す)。「1件ずつ
   `What-if`を聞く」のではなく「安全な追加・危険な追加を全部リストアップする」形。
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


def _excess_by_agent(reachable: dict[str, int], intended_max_tier: dict[str, int]) -> dict[str, int]:
    return {agent_id: max(0, tier - intended_max_tier[agent_id]) for agent_id, tier in reachable.items()}


def _total_excess(reachable: dict[str, int], intended_max_tier: dict[str, int]) -> int:
    return sum(_excess_by_agent(reachable, intended_max_tier).values())


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


@dataclass
class CandidateGrantResult:
    """まだ存在しない新規trust宣言を1件追加した場合の効果(事前チェック)。"""

    truster_agent_id: str
    """新たにtrustを与える側(現在delegate_to=Noneのエージェント)。"""

    trusted_agent_id: str
    """新たに信頼される相手(truster_agent_idをassumeできるようになる側)。"""

    newly_escalated_agent_ids: list[str]
    """この追加によって、新たに権限昇格状態になるエージェントのID一覧。"""

    worsened_agent_ids: list[str]
    """既に権限昇格していたが、この追加でさらに超過tierが悪化するエージェント。"""

    excess_introduced: int
    """この追加によって新たに生まれる、超過tierの合計(新規昇格+既存昇格の悪化分)。
    ランキングの並び順に使う——数値が大きいほど危険な追加。"""

    is_safe: bool
    """新規昇格も悪化も一切生まない(=追加しても安全)場合True。"""


def scan_candidate_trust_grants(
    engine: PrivilegeDelegationEngine, declarations: list[Declaration]
) -> list[CandidateGrantResult]:
    """まだtrustを与えていない(delegate_to=None)エージェントについて、
    「もしこの相手を新たに信頼したら」という候補を総当たりし、権限昇格を
    新たに生む危険な追加はどれかを一括でスキャンする(excess_introduced降順)。

    rank_chokepoint_edgesの逆方向: あちらは「既存のedgeを取り除いたら」(事後・
    根本原因の特定)、こちらは「まだ無いedgeを追加したら」(事前・危険な変更の
    先回り検出)。delegate_toが既に設定されているエージェントについては、
    「1対1の信頼」という現行スキーマの単純化(D-60)のもとでは「差し替え」に
    なり「追加」ではないため、スキャン対象に含めない。計測のみ(実際にtrust
    宣言を書き換えたり環境に書き込んだりはしない)。
    """
    baseline_reachable = engine.resolve_reachable_tiers(declarations)
    baseline_excess = _excess_by_agent(baseline_reachable, engine.parameters.intended_max_tier)

    by_agent = {d.agent_id: d for d in declarations}
    agent_ids = list(engine.parameters.tiers.keys())
    untrusting_agents = [a for a in agent_ids if by_agent.get(a) is None or by_agent[a].delegate_to is None]

    results: list[CandidateGrantResult] = []
    for truster in untrusting_agents:
        for trusted in agent_ids:
            if trusted == truster:
                continue
            modified = [
                Declaration(
                    agent_id=d.agent_id,
                    delegate_to=(trusted if d.agent_id == truster else d.delegate_to),
                )
                for d in declarations
            ]
            reachable_with = engine.resolve_reachable_tiers(modified)
            excess_with = _excess_by_agent(reachable_with, engine.parameters.intended_max_tier)

            newly_escalated = sorted(
                a for a, e in excess_with.items() if e > 0 and baseline_excess.get(a, 0) == 0
            )
            worsened = sorted(
                a for a, e in excess_with.items() if baseline_excess.get(a, 0) > 0 and e > baseline_excess[a]
            )
            excess_introduced = sum(
                excess_with[a] - baseline_excess.get(a, 0)
                for a in excess_with
                if excess_with[a] > baseline_excess.get(a, 0)
            )

            results.append(
                CandidateGrantResult(
                    truster_agent_id=truster,
                    trusted_agent_id=trusted,
                    newly_escalated_agent_ids=newly_escalated,
                    worsened_agent_ids=worsened,
                    excess_introduced=excess_introduced,
                    is_safe=(not newly_escalated and not worsened),
                )
            )

    results.sort(key=lambda r: r.excess_introduced, reverse=True)
    return results
