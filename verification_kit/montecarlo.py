"""検証キット: モンテカルロによる耐戦略性の経験的頑健性チェック
(実証的検証サブコンポーネント、verification_layer_clarification.md 2章)。

1回性エンジンでは「収束確率」の代わりに、様々な入力パターンで逸脱が得に
ならないかを統計的に確認する役割を担う(SMAS_theorymap.md 2.1節)。
5大指標③頑健性の根拠(CLAUDE.md 10章: モンテカルロ結果の要約、逸脱が
得になったケース数)を、そのまま計算する共通実装。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from schemas.incentive_schema import AllocationResult, Declaration, IncentiveEngine


@dataclass
class DeviationTrialResult:
    honest_utility: float
    deviated_utility: float
    deviation_was_profitable: bool


def utility(agent_id: str, true_value: float, result: AllocationResult) -> float:
    """配分を得た場合: 真の価値 - 支払い。得なかった場合: 0。"""
    if agent_id not in result.allocated_agent_ids:
        return 0.0
    return true_value - result.payments.get(agent_id, 0.0)


def run_trials(
    engine: IncentiveEngine,
    make_honest_declarations: Callable[[], list[Declaration]],
    deviate: Callable[[list[Declaration]], list[Declaration]],
    true_values: dict[str, float],
    target_agent_id: str,
    n_trials: int = 1000,
) -> list[DeviationTrialResult]:
    """target_agent_id が逸脱した場合としなかった場合の効用を、n_trials回比較する。"""
    trials: list[DeviationTrialResult] = []
    for _ in range(n_trials):
        honest = make_honest_declarations()
        honest_result = engine.allocate_and_pay(honest)
        honest_u = utility(target_agent_id, true_values[target_agent_id], honest_result)

        deviated = deviate(honest)
        deviated_result = engine.allocate_and_pay(deviated)
        deviated_u = utility(target_agent_id, true_values[target_agent_id], deviated_result)

        trials.append(
            DeviationTrialResult(
                honest_utility=honest_u,
                deviated_utility=deviated_u,
                deviation_was_profitable=deviated_u > honest_u,
            )
        )
    return trials


def summarize(trials: list[DeviationTrialResult]) -> dict:
    """5大指標③頑健性の1行サマリーに使う集計。"""
    profitable = sum(t.deviation_was_profitable for t in trials)
    return {
        "n_trials": len(trials),
        "profitable_deviation_count": profitable,
        "profitable_deviation_rate": profitable / len(trials) if trials else 0.0,
    }
