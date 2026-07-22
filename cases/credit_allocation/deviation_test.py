"""逸脱注入テストのシナリオ(4シーン構成、信用枠配分ケース)。

    ============================================================
    このケースの4シーン構成は、ケース1(3シーン)を繰り返しゲームの性質に
    合わせて拡張したもの。トリガー発動と回復を独立したシーンとして切り出す。
    ============================================================

シーン1(構築期): 全員が信用枠を遵守し続け、信用枠が定常状態に近づくまで
シーン2(逸脱注入): 1エージェントが信用枠を無視した固定高値の申告を開始する
シーン3(トリガー発動): 直近の違反により信用枠が制裁水準まで縮小する
シーン4(回復): 遵守に戻り、信用枠が徐々に回復する

ケース1の「反実仮想比較」に対応する立証ポイントとして、シーン2以降の合計の
割引後効用を「逸脱した場合」と「シーン2以降もずっと遵守していた場合」で比較する
(RepeatedGameComparison)。この比較は2回の独立したシミュレーション(実際に逸脱
させた環境と、遵守を貫いた環境)を、それぞれ別のEnvironmentClientで実行して行う
——ケース1の単一ラウンド反実仮想比較と異なり、このケースは信用枠が履歴依存
(過去のラウンドが将来の信用枠に影響する)ため、ラウンド単位の分岐では比較でき
ない(D-07で確認した「1回性と繰り返しゲームの混在を避ける」原則をここでも守る)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aggregation import run_mechanism
from agents.rule_based import GreedyOverstatingAgent
from environment import EnvironmentClient
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import Trace
from schemas.incentive_schema import AllocationResult, Declaration

from credit_agents import CreditAwareHonestAgent
from incentive_engine import CreditLimitResult, TriggerStrategyEngine, compute_credit_limit
from payloads import CreditRoundRecord


@dataclass
class RoundResult:
    name: str
    round_id: int
    declarations: list[Declaration]
    credit_limits: dict[str, CreditLimitResult]
    outcome: AllocationResult | None
    compliance: dict[str, bool]
    terminated_by_fallback: bool


def run_round(
    name: str,
    agents: list[Agent],
    engine: TriggerStrategyEngine,
    env: EnvironmentClient,
) -> RoundResult:
    """1ラウンド分: 信用枠の算出→申告収集→配分実行→記録の書き込み。"""
    round_id = env.advance_round()

    credit_limits = {
        agent.agent_id: compute_credit_limit(env, agent.agent_id, round_id, engine.parameters)
        for agent in agents
    }

    declarations: list[Declaration] = []
    for agent in agents:
        trace_summary = {"round": round_id, "credit_limit": credit_limits[agent.agent_id].credit_limit}
        observation = ObservationInput(trace_summary=trace_summary)
        action = agent.decide(observation)
        declarations.append(Declaration(agent_id=agent.agent_id, declared_value=action.declared_value))

    outcome = run_mechanism(engine, declarations)

    compliance: dict[str, bool] = {}
    winners = set(outcome.result.allocated_agent_ids) if outcome.result else set()
    for declaration in declarations:
        limit = credit_limits[declaration.agent_id].credit_limit
        compliant = declaration.declared_value <= limit + 1e-9
        compliance[declaration.agent_id] = compliant
        record = CreditRoundRecord(
            declared_value=declaration.declared_value,
            credit_limit_at_declaration=limit,
            won=declaration.agent_id in winners,
            compliant=compliant,
        )
        env.write_trace(
            writer_id=declaration.agent_id,
            trace=Trace(agent_id=declaration.agent_id, round_id=round_id, payload=record),
        )

    return RoundResult(
        name=name,
        round_id=round_id,
        declarations=declarations,
        credit_limits=credit_limits,
        outcome=outcome.result,
        compliance=compliance,
        terminated_by_fallback=outcome.terminated_by_fallback,
    )


@dataclass
class RepeatedGameComparison:
    """シーン2以降(逸脱注入〜回復)の、逸脱あり/なしの割引後合計効用比較。"""

    deviating_agent_id: str
    discount: float
    actual_utility: float = 0.0
    counterfactual_utility: float = 0.0

    @property
    def deviation_profitable(self) -> bool:
        """逸脱の割引後合計効用が、遵守を貫いた場合を上回ったか。Trueなら反例。"""
        return self.actual_utility > self.counterfactual_utility


def _run_scenes(
    agent_ids: list[str],
    engine: TriggerStrategyEngine,
    env: EnvironmentClient,
    *,
    deviating_agent_id: str | None,
    build_rounds: int,
    deviate_rounds: int,
    punishment_rounds: int,
    recover_rounds: int,
    high_value: float = 15.0,
    low_value: float = 8.0,
) -> list[RoundResult]:
    """4シーン構成を1回分実行する。deviating_agent_id=Noneなら、シーン2以降も
    全員遵守を貫く反実仮想トラジェクトリになる。high_value/low_valueはモンテカルロ
    (真の評価額の分布を変えた頑健性チェック、generate_results_summary.py)向けに
    差し替え可能にしている。"""
    honest_agents = [
        CreditAwareHonestAgent(agent_id, index, n_agents=len(agent_ids), high_value=high_value, low_value=low_value)
        for index, agent_id in enumerate(agent_ids)
    ]
    results: list[RoundResult] = []

    for _ in range(build_rounds):
        results.append(run_round("scene1_build", honest_agents, engine, env))

    if deviating_agent_id is not None:
        deviating_agents = [
            GreedyOverstatingAgent(a.agent_id, fixed_declared_value=1000.0)
            if a.agent_id == deviating_agent_id
            else a
            for a in honest_agents
        ]
        for _ in range(deviate_rounds):
            results.append(run_round("scene2_deviation_injected", deviating_agents, engine, env))
    else:
        for _ in range(deviate_rounds):
            results.append(run_round("scene2_counterfactual_honest", honest_agents, engine, env))

    for _ in range(punishment_rounds):
        results.append(run_round("scene3_trigger_active", honest_agents, engine, env))
    for _ in range(recover_rounds):
        results.append(run_round("scene4_recovery", honest_agents, engine, env))

    return results


def run_four_scene_demo(
    agent_ids: list[str],
    deviating_agent_id: str,
    engine: TriggerStrategyEngine,
    env_factory,
    *,
    build_rounds: int = 10,
    deviate_rounds: int = 5,
    punishment_rounds: int = 5,
    recover_rounds: int = 10,
    discount: float = 0.9,
    high_value: float = 15.0,
    low_value: float = 8.0,
) -> tuple[list[RoundResult], RepeatedGameComparison]:
    """実際の逸脱トラジェクトリ(env_factory()で新規環境)と、遵守を貫いた反実仮想
    トラジェクトリ(別の新規環境)をそれぞれ実行し、シーン2以降の割引後合計効用を比較する。

    env_factory は EnvironmentClient を新規生成する関数(呼び出し側が
    config.yamlのEnvironmentConfigから構築したものを都度渡す)。
    """
    actual_env = env_factory()
    actual_results = _run_scenes(
        agent_ids, engine, actual_env,
        deviating_agent_id=deviating_agent_id,
        build_rounds=build_rounds, deviate_rounds=deviate_rounds,
        punishment_rounds=punishment_rounds, recover_rounds=recover_rounds,
        high_value=high_value, low_value=low_value,
    )

    counterfactual_env = env_factory()
    counterfactual_results = _run_scenes(
        agent_ids, engine, counterfactual_env,
        deviating_agent_id=None,
        build_rounds=build_rounds, deviate_rounds=deviate_rounds,
        punishment_rounds=punishment_rounds, recover_rounds=recover_rounds,
        high_value=high_value, low_value=low_value,
    )

    true_value_schedule = CreditAwareHonestAgent(
        deviating_agent_id,
        agent_ids.index(deviating_agent_id),
        n_agents=len(agent_ids),
        high_value=high_value, low_value=low_value,
    )

    comparison = RepeatedGameComparison(deviating_agent_id=deviating_agent_id, discount=discount)
    post_build_actual = [r for r in actual_results if r.name != "scene1_build"]
    post_build_counterfactual = [r for r in counterfactual_results if r.name != "scene1_build"]

    for t, round_result in enumerate(post_build_actual):
        won = round_result.outcome is not None and deviating_agent_id in round_result.outcome.allocated_agent_ids
        true_value = true_value_schedule.true_value_for_round(round_result.round_id)
        comparison.actual_utility += (discount ** t) * (true_value if won else 0.0)

    for t, round_result in enumerate(post_build_counterfactual):
        won = round_result.outcome is not None and deviating_agent_id in round_result.outcome.allocated_agent_ids
        true_value = true_value_schedule.true_value_for_round(round_result.round_id)
        comparison.counterfactual_utility += (discount ** t) * (true_value if won else 0.0)

    return actual_results, comparison


@dataclass
class SustainedStrategyComparison:
    """D-37の発見(信用枠内に留まる恒常的な過大申告は一度も検出されない)の頑健性
    チェック用。4シーン構成(build→deviate→punish→recover)とは異なり、この戦略は
    「遵守」判定を一度も破らないため制裁が発動せず、シーン分割そのものが不要になる
    ——全ラウンドを同一の戦略で押し通した場合の割引後合計効用を、honestのまま
    貫いた場合(反実仮想)と比較するだけでよい。
    """

    agent_id: str
    discount: float
    strategy_utility: float = 0.0
    honest_utility: float = 0.0

    @property
    def strategy_profitable(self) -> bool:
        return self.strategy_utility > self.honest_utility


def run_sustained_strategy_comparison(
    agent_ids: list[str],
    strategy_agent_id: str,
    strategy_agent_factory,
    engine: TriggerStrategyEngine,
    env_factory,
    *,
    n_rounds: int,
    discount: float,
    high_value: float = 15.0,
    low_value: float = 8.0,
) -> SustainedStrategyComparison:
    """strategy_agent_idだけを指定した戦略(strategy_agent_factory(agent_id)で生成)
    に差し替えたまま全ラウンドを実行した場合と、honestのまま貫いた場合(反実仮想、
    別のEnvironmentClientで独立実行)を、それぞれn_rounds回実行して比較する。
    """

    def make_honest_agents() -> list[Agent]:
        return [
            CreditAwareHonestAgent(a, i, n_agents=len(agent_ids), high_value=high_value, low_value=low_value)
            for i, a in enumerate(agent_ids)
        ]

    true_value_schedule = CreditAwareHonestAgent(
        strategy_agent_id,
        agent_ids.index(strategy_agent_id),
        n_agents=len(agent_ids),
        high_value=high_value, low_value=low_value,
    )

    strategy_env = env_factory()
    strategy_agents = [
        strategy_agent_factory(agent_id) if agent_id == strategy_agent_id else agent
        for agent_id, agent in zip(agent_ids, make_honest_agents())
    ]
    strategy_results = [run_round("sustained_strategy", strategy_agents, engine, strategy_env) for _ in range(n_rounds)]

    honest_env = env_factory()
    honest_agents = make_honest_agents()
    honest_results = [run_round("sustained_honest", honest_agents, engine, honest_env) for _ in range(n_rounds)]

    comparison = SustainedStrategyComparison(agent_id=strategy_agent_id, discount=discount)
    for t, round_result in enumerate(strategy_results):
        won = round_result.outcome is not None and strategy_agent_id in round_result.outcome.allocated_agent_ids
        true_value = true_value_schedule.true_value_for_round(round_result.round_id)
        comparison.strategy_utility += (discount ** t) * (true_value if won else 0.0)
    for t, round_result in enumerate(honest_results):
        won = round_result.outcome is not None and strategy_agent_id in round_result.outcome.allocated_agent_ids
        true_value = true_value_schedule.true_value_for_round(round_result.round_id)
        comparison.honest_utility += (discount ** t) * (true_value if won else 0.0)

    return comparison
