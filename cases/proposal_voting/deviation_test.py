"""ケース3の逸脱注入シナリオ(2シーン構成)。

ケース1・2の「逸脱は損をする(自己拘束)」の実証とは狙いが逆で、ボルダ得点が
理論どおり非耐戦略性メカニズムであることを実地で示す(D-27、
mechanism_catalog.md Part3)。⑤検証層・③モンテカルロが「悪い設計」を
正しく検出できるかを確認するための素材として位置づける。

シーン1(平常時): 全員が真の評価額どおりの順位を申告→ボルダ集計→採用決定
シーン2(逸脱注入): 1エージェントが「埋葬」戦術(voting_agents.BuryingStrategicAgent)
  で申告し、実現効用を正直申告時の効用(反実仮想)と比較する。honest_agentsは
  申告時にobservation(trace_summary)を一切使わないため、実際の申告後に
  反実仮想側を計算しても結果は変わらない(順序の入れ替えが結論に影響しない)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from environment import EnvironmentClient
from langgraph_flow import VotingSceneResult, run_voting_round
from schemas.agent_schema import Agent, ObservationInput
from schemas.incentive_schema import AllocationResult, Declaration, IncentiveEngine


@dataclass
class RoundComparison:
    round_id: int
    actual_utility: float
    counterfactual_utility: float


@dataclass
class ManipulationReport:
    """シーン2の集計。計測のみで、配分には影響しない(CLAUDE.md 9章と同じ位置づけ)。"""

    manipulating_agent_id: str
    rounds: list[RoundComparison] = field(default_factory=list)

    @property
    def total_actual_utility(self) -> float:
        return sum(r.actual_utility for r in self.rounds)

    @property
    def total_counterfactual_utility(self) -> float:
        return sum(r.counterfactual_utility for r in self.rounds)

    @property
    def manipulation_profitable(self) -> bool:
        """埋葬戦術の合計効用が、正直申告時(反実仮想)を上回ったか。

        ケース1・2のdeviation_profitableと違い、Trueが「理論どおりの想定内の
        結果」であることに注意(ボルダ得点は非耐戦略性メカニズム)。
        """
        return self.total_actual_utility > self.total_counterfactual_utility


def _utility(true_values: dict[str, float], result: AllocationResult | None) -> float:
    if result is None or not result.allocated_agent_ids:
        return 0.0
    winner = result.allocated_agent_ids[0]
    return true_values.get(winner, 0.0)


def run_two_scene_demo(
    honest_agents: list[Agent],
    manipulating_agent_id: str,
    manipulating_agent_factory,
    manipulating_agent_true_values: dict[str, float],
    engine: IncentiveEngine,
    env: EnvironmentClient,
    *,
    scene1_rounds: int = 5,
    scene2_rounds: int = 5,
) -> tuple[list[VotingSceneResult], ManipulationReport]:
    results: list[VotingSceneResult] = []

    for _ in range(scene1_rounds):
        results.append(run_voting_round("scene1_honest", honest_agents, engine, env))

    manipulating_agents = [
        manipulating_agent_factory(a) if a.agent_id == manipulating_agent_id else a
        for a in honest_agents
    ]
    report = ManipulationReport(manipulating_agent_id=manipulating_agent_id)

    for _ in range(scene2_rounds):
        actual = run_voting_round("scene2_manipulation_injected", manipulating_agents, engine, env)
        results.append(actual)

        trace_summary = {"round": env.current_round, "history_size": len(env.read_traces())}
        counterfactual_declarations = [
            Declaration(
                agent_id=a.agent_id,
                declared_ranking=a.decide(ObservationInput(trace_summary=trace_summary)).declared_ranking,
            )
            for a in honest_agents
        ]
        counterfactual_result = engine.allocate_and_pay(counterfactual_declarations)

        report.rounds.append(
            RoundComparison(
                round_id=env.current_round,
                actual_utility=_utility(manipulating_agent_true_values, actual.outcome.result),
                counterfactual_utility=_utility(manipulating_agent_true_values, counterfactual_result),
            )
        )

    return results, report
