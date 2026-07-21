"""③集約層(メカニズム実行層): ①環境層から読み取り、②誘因構造層の定義層ルールを
計算・適用する共通実装。

決定論的関数を各エージェントがローカルに同じ計算をする前提(中央が計算しない、
architecture_overview.md「集約層」の集権化させないための原則)。

打ち切りルール(最大試行回数・タイムアウト・フォールバック)を必ず実装する
(CLAUDE.md 8章)。打ち切りルール自体が意図的に収束を遅らせて得をする、新たな
逸脱の温床にならないよう、フォールバックは申告内容に依存しない固定の挙動にする。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from schemas.incentive_schema import AllocationResult, Declaration, IncentiveEngine


@dataclass
class TerminationConfig:
    """③集約層の打ち切りルール(CLAUDE.md 8章、必須)。"""

    max_iterations: int = 1
    timeout_seconds: float = 5.0


@dataclass
class AggregationOutcome:
    result: AllocationResult | None
    iterations_used: int
    elapsed_seconds: float
    terminated_by_fallback: bool
    last_error: str | None = None


def run_mechanism(
    engine: IncentiveEngine,
    declarations: list[Declaration],
    termination: TerminationConfig | None = None,
    fallback: AllocationResult | None = None,
) -> AggregationOutcome:
    """②誘因構造エンジンを実行し、打ち切りルールに従って結果またはフォールバックを返す。

    フォールバックは呼び出し側が固定値として渡す(既定は「誰にも配分しない」)。
    申告内容を見て動的にフォールバック挙動を変えると、それ自体が新たな逸脱の
    温床になりうるため、意図的にこの関数の外(呼び出し側の固定引数)に置く
    (evaluation_criteria.md #23 打ち切り耐性)。
    """
    termination = termination or TerminationConfig()
    fallback = fallback if fallback is not None else AllocationResult(allocated_agent_ids=[], payments={})

    start = time.monotonic()
    last_error: Exception | None = None
    for iteration in range(1, termination.max_iterations + 1):
        elapsed = time.monotonic() - start
        if elapsed > termination.timeout_seconds:
            last_error = TimeoutError(f"timeout after {elapsed:.3f}s")
            break
        try:
            result = engine.allocate_and_pay(declarations)
        except Exception as exc:  # noqa: BLE001 - 打ち切りルールの対象として捕捉する
            last_error = exc
            continue
        return AggregationOutcome(
            result=result,
            iterations_used=iteration,
            elapsed_seconds=time.monotonic() - start,
            terminated_by_fallback=False,
        )

    return AggregationOutcome(
        result=fallback,
        iterations_used=termination.max_iterations,
        elapsed_seconds=time.monotonic() - start,
        terminated_by_fallback=True,
        last_error=str(last_error) if last_error else None,
    )


def aggregate_by_ranking(agent_ids: list[str], rankings: list[list[str]]) -> str:
    """③集約層の別経路: 支払いを伴わない投票メカニズム向け(pref_voting利用)。

    「支払い」という概念がそもそも存在しないメカニズムでも、この層が同じ責務
    (決定論的な集約)を果たせることを示す(mechanism_catalog.md ファミリー2)。
    ボルダ得点で単一の勝者を返す。同点の場合は agent_ids の順で先着を採用する。
    """
    from pref_voting.profiles import Profile
    from pref_voting.scoring_methods import borda

    index_of = {agent_id: i for i, agent_id in enumerate(agent_ids)}
    ballots = [[index_of[a] for a in ranking] for ranking in rankings]
    profile = Profile(ballots)
    winners = borda(profile)
    winner_index = min(winners)
    return agent_ids[winner_index]
