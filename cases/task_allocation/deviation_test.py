"""逸脱注入テストのシナリオ(3シーン構成、CLAUDE.md 9章、DECISIONS.md D-07)。

    ============================================================
    このtemplateをフォークしたら、シーンの意味づけ(逸脱の種類・
    「逸脱が得にならない」と判定する効用差の基準)をケースに合わせて書き換える。
    ============================================================

シーン1(平常時): 正直申告 → 集約 → 配分決定
シーン2(逸脱注入): 1エージェントが過大申告(戦略的逸脱)
シーン3(自己拘束の確認): 同一ラウンド内で、逸脱エージェントの実現効用を
  正直申告時の効用(反実仮想)と比較し、「逸脱しても得をしない(むしろ損をする)」
  ことを数値で示す(耐戦略性の直接実証)

旧シーン3(痕跡→信用低下→取引忌避という間接修正)は、繰り返しゲームが主軸の
2ケース目に移設した(DECISIONS.md D-07)。その名残である信用ゲート
(engine.incentive_engine.filter_eligible_declarations)は「2ケース目のプレビュー」
として engine/ 側に残っているが、このシナリオランナーはもう使わない
(理由は engine/incentive_engine.py の該当セクションのコメント参照)。

シーン3の反実仮想比較は「計測・ログ出力」であり、メカニズムの構成要素ではない
(配分・支払いには一切影響しない。CLAUDE.md 9章)。逸脱エージェントの真の評価額は、
正直版エージェント(honest_agents)が同一ラウンドで申告したはずの値として得る
(「正直申告=真の評価額の申告」という定義そのものを利用しており、観測不可能な
情報への不正なアクセスをシミュレーション外から持ち込んでいない)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aggregation import AggregationOutcome, TerminationConfig, run_mechanism
from environment import EnvironmentClient
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import Trace
from schemas.incentive_schema import AllocationResult, Declaration, IncentiveEngine, ParticipationRecord


@dataclass
class SceneResult:
    name: str
    outcome: AggregationOutcome
    declarations: list[Declaration]


@dataclass
class RoundComparison:
    """シーン2の1ラウンド分の、逸脱あり(実現)/全員正直(反実仮想)の効用比較。"""

    round_id: int
    actual_utility: float
    counterfactual_utility: float


@dataclass
class SelfEnforcementReport:
    """シーン3(自己拘束の確認)の集計。計測のみで、配分には影響しない。"""

    deviating_agent_id: str
    rounds: list[RoundComparison] = field(default_factory=list)

    @property
    def total_actual_utility(self) -> float:
        return sum(r.actual_utility for r in self.rounds)

    @property
    def total_counterfactual_utility(self) -> float:
        return sum(r.counterfactual_utility for r in self.rounds)

    @property
    def deviation_profitable(self) -> bool:
        """逸脱の合計効用が正直申告時(反実仮想)を上回ったか。Trueなら耐戦略性の反例。"""
        return self.total_actual_utility > self.total_counterfactual_utility


def _collect_declarations(
    agents: list[Agent], env: EnvironmentClient, round_id: int
) -> list[Declaration]:
    trace_summary = {"round": round_id, "history_size": len(env.read_traces())}
    declarations: list[Declaration] = []
    for agent in agents:
        observation = ObservationInput(trace_summary=trace_summary)
        action = agent.decide(observation)
        declarations.append(Declaration(agent_id=agent.agent_id, declared_value=action.declared_value))
    return declarations


def _utility(agent_id: str, true_value: float, result: AllocationResult | None) -> float:
    """準線形効用(効用=真の評価額−支払い。落選なら0)。VCGの適用前提
    (scope_exclusions_and_deferrals.md Part 0「効用の準線形性」)をそのまま使う。"""
    if result is None or agent_id not in result.allocated_agent_ids:
        return 0.0
    return true_value - result.payments.get(agent_id, 0.0)


def _record_participation(
    env: EnvironmentClient, declarations: list[Declaration], outcome: AggregationOutcome, round_id: int
) -> None:
    """参加記録を公開痕跡として書き込む(①環境層の疎通確認。1ケース目では
    この痕跡を配分判断に使わない。eligible は常にTrue=信用ゲート不使用)。"""
    winners = set(outcome.result.allocated_agent_ids) if outcome.result else set()
    payments = outcome.result.payments if outcome.result else {}
    for declaration in declarations:
        record = ParticipationRecord(
            declared_value=declaration.declared_value,
            won=declaration.agent_id in winners,
            payment=payments.get(declaration.agent_id, 0.0),
            eligible=True,
        )
        env.write_trace(
            writer_id=declaration.agent_id,
            trace=Trace(agent_id=declaration.agent_id, round_id=round_id, payload=record),
        )


def run_scene(
    name: str,
    agents: list[Agent],
    engine: IncentiveEngine,
    env: EnvironmentClient,
    termination: TerminationConfig | None = None,
) -> SceneResult:
    """1シーン(1ラウンド)分: 申告収集→集約実行→参加記録の書き込み。"""
    round_id = env.advance_round()
    declarations = _collect_declarations(agents, env, round_id)
    outcome = run_mechanism(engine, declarations, termination=termination)
    _record_participation(env, declarations, outcome, round_id)
    return SceneResult(name=name, outcome=outcome, declarations=declarations)


def run_three_scene_demo(
    honest_agents: list[Agent],
    deviating_agent_id: str,
    deviating_agent_factory,
    engine: IncentiveEngine,
    env: EnvironmentClient,
    *,
    scene1_rounds: int = 5,
    scene2_rounds: int = 5,
    termination: TerminationConfig | None = None,
) -> tuple[list[SceneResult], SelfEnforcementReport]:
    """シーン1〜3を通しで実行する、最小の疎通確認ランナー。

    deviating_agent_id で指定した1エージェントだけを、deviating_agent_factory
    (例: lambda a: GreedyOverstatingAgent(a.agent_id)) で逸脱するエージェントに
    差し替える(CLAUDE.md 9章「1エージェントが過大申告」)。

    シーン2の各ラウンドで、同じ観測に対する「全員正直の申告(反実仮想)」も収集し、
    ②誘因構造エンジンを純関数として両方に適用して効用差を計測する。環境
    (ラウンド進行・痕跡書き込み)は実現側(逸脱あり)でのみ更新し、反実仮想側は
    計測のみに使う(メカニズムの構成要素にしない)。

    戻り値はシーン1・2の実行結果リストと、シーン3にあたる SelfEnforcementReport。
    """
    results: list[SceneResult] = []

    for _ in range(scene1_rounds):
        results.append(run_scene("scene1_honest", honest_agents, engine, env, termination))

    deviating_agents = [
        deviating_agent_factory(a) if a.agent_id == deviating_agent_id else a for a in honest_agents
    ]
    report = SelfEnforcementReport(deviating_agent_id=deviating_agent_id)

    for _ in range(scene2_rounds):
        round_id = env.advance_round()
        actual_declarations = _collect_declarations(deviating_agents, env, round_id)
        counterfactual_declarations = _collect_declarations(honest_agents, env, round_id)

        outcome = run_mechanism(engine, actual_declarations, termination=termination)
        _record_participation(env, actual_declarations, outcome, round_id)
        results.append(SceneResult("scene2_deviation_injected", outcome, actual_declarations))

        # シーン3(計測): 逸脱者の真の評価額=正直版が同一ラウンドで申告したはずの値
        true_value = next(
            d.declared_value for d in counterfactual_declarations if d.agent_id == deviating_agent_id
        )
        counterfactual_result = engine.allocate_and_pay(counterfactual_declarations)
        report.rounds.append(
            RoundComparison(
                round_id=round_id,
                actual_utility=_utility(deviating_agent_id, true_value, outcome.result if outcome.result else None),
                counterfactual_utility=_utility(deviating_agent_id, true_value, counterfactual_result),
            )
        )

    return results, report
