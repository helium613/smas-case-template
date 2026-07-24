"""ケース5のシナリオ(3シーン構成、CLAUDE.md 9章の枠組みを本ケース向けに再解釈)。

ケース1〜4の「1エージェントの逸脱・操作」という筋書きとは異なり、このケースの
主眼は**誰も虚偽申告していないのに、複数の個別には正当なtrust宣言が合成される
ことで、誰も意図しない権限昇格経路が生まれるか**にある(confused deputy)。

シーン1(平常時): 各ロールが業務上必要な最小限のtrust宣言をする。到達可能tierは
  全員 intended_max_tier と一致し、昇格は発生しない。
シーン2(合成リスク注入): 既存の正直な宣言はそのまま、1件のtrust宣言だけを追加
  する(単独では局所的に正当に見える判断)。この1件が既存の宣言と組み合わさり、
  誰も意図していない権限昇格経路が生まれる。
シーン3(根本原因の特定、反実仮想): シーン2から注入した1件のtrust宣言だけを
  取り除いた場合の到達可能性を計測し、「その1件を除けば昇格経路は消える」ことを
  示す。効用比較ではなく到達可能性の比較になる点が、支払い概念を持たない
  このケース固有の反実仮想の適応(計測のみ、メカニズムの構成要素にはしない)。
"""
from __future__ import annotations

from dataclasses import dataclass

from aggregation import AggregationOutcome, TerminationConfig, run_mechanism
from environment import EnvironmentClient
from incentive_engine import PrivilegeDelegationEngine
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import Trace
from schemas.incentive_schema import Declaration

from delegation_agents import TrustDeclaringAgent


@dataclass
class SceneResult:
    name: str
    outcome: AggregationOutcome
    reachable: dict[str, int]
    declarations: list[Declaration]


@dataclass
class EscalationReport:
    scene2_escalated: list[str]
    scene2_reachable: dict[str, int]
    scene3_counterfactual_reachable: dict[str, int]
    root_cause_agent_id: str
    root_cause_confirmed: bool
    """シーン2で注入した1件のtrust宣言を取り除くと、昇格が完全に消えるか。"""


def _collect_declarations(agents: list[Agent], env: EnvironmentClient, round_id: int) -> list[Declaration]:
    """申告を収集する。`decide_all`を持つエージェント(ファンアウト対応、D-80)は
    複数のDeclarationを返す——同じagent_idの複数件が混在しても、エンジン側は
    無改造でそのまま扱える(D-80で実証済み)。持たないエージェントは従来どおり
    `decide()`1回で1件。
    """
    trace_summary = {"round": round_id, "history_size": len(env.read_traces())}
    declarations: list[Declaration] = []
    observation = ObservationInput(trace_summary=trace_summary)
    for agent in agents:
        if hasattr(agent, "decide_all"):
            actions = agent.decide_all(observation)
        else:
            actions = [agent.decide(observation)]
        for action in actions:
            declarations.append(Declaration(agent_id=agent.agent_id, delegate_to=action.delegate_to))
    return declarations


def run_scene(
    name: str,
    agents: list[Agent],
    engine: PrivilegeDelegationEngine,
    env: EnvironmentClient,
    termination: TerminationConfig | None = None,
) -> SceneResult:
    """1シーン(1ラウンド)分: trust宣言収集→到達可能性解決→集約実行→痕跡の書き込み。"""
    round_id = env.advance_round()
    declarations = _collect_declarations(agents, env, round_id)
    reachable = engine.resolve_reachable_tiers(declarations)
    outcome = run_mechanism(engine, declarations, termination=termination)
    for declaration in declarations:
        env.write_trace(
            writer_id=declaration.agent_id,
            trace=Trace(
                agent_id=declaration.agent_id,
                round_id=round_id,
                payload=declaration,
                process_trace={"reachable_tier": reachable.get(declaration.agent_id)},
            ),
        )
    return SceneResult(name=name, outcome=outcome, reachable=reachable, declarations=declarations)


def run_three_scene_demo(
    baseline_agents: list[TrustDeclaringAgent],
    injected_agent_id: str,
    injected_delegate_to: str,
    engine: PrivilegeDelegationEngine,
    env: EnvironmentClient,
    *,
    scene1_rounds: int = 3,
    scene2_rounds: int = 3,
    termination: TerminationConfig | None = None,
) -> tuple[list[SceneResult], EscalationReport]:
    """シーン1〜3を通しで実行する。baseline_agentsのうちinjected_agent_idのtrust宣言
    のみを、シーン2でinjected_delegate_toに差し替える(baseline_agentsではNoneだった
    前提、シーン3の反実仮想はこれを再びNoneに戻して比較する)。
    """
    results: list[SceneResult] = []
    for _ in range(scene1_rounds):
        results.append(run_scene("scene1_baseline", baseline_agents, engine, env, termination))

    injected_agents = [
        TrustDeclaringAgent(a.agent_id, injected_delegate_to) if a.agent_id == injected_agent_id else a
        for a in baseline_agents
    ]
    for _ in range(scene2_rounds):
        results.append(run_scene("scene2_trust_injected", injected_agents, engine, env, termination))

    scene2_result = results[-1]
    scene2_escalated = sorted(scene2_result.outcome.result.allocated_agent_ids) if scene2_result.outcome.result else []

    # シーン3(計測): 注入した1件の宣言だけを取り除いた場合(シーン1相当の宣言)の
    # 到達可能性を、メカニズムを介さず直接計算する(環境への書き込みは行わない、
    # CLAUDE.md 9章「反実仮想比較は計測・ログ出力として実装し、メカニズムの
    # 構成要素にしない」)。
    counterfactual_declarations = [
        Declaration(
            agent_id=d.agent_id,
            delegate_to=(None if d.agent_id == injected_agent_id else d.delegate_to),
        )
        for d in scene2_result.declarations
    ]
    counterfactual_reachable = engine.resolve_reachable_tiers(counterfactual_declarations)
    root_cause_confirmed = all(
        counterfactual_reachable[agent_id] <= engine.parameters.intended_max_tier[agent_id]
        for agent_id in counterfactual_reachable
    )

    report = EscalationReport(
        scene2_escalated=scene2_escalated,
        scene2_reachable=scene2_result.reachable,
        scene3_counterfactual_reachable=counterfactual_reachable,
        root_cause_agent_id=injected_agent_id,
        root_cause_confirmed=root_cause_confirmed,
    )
    return results, report
