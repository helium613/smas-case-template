"""ケース6のシナリオ(3シーン構成、CLAUDE.md 9章の枠組みを本ケース向けに再解釈)。

ケース5(IAM委任チェーン)は「1件のtrust宣言の追加(新しい辺の出現)」が合成
リスクを注入したが、このケースの委任グラフは最初から固定(新しい辺は増えない)。
代わりに、**既存の1本の委任辺の"金額"を、委任元が「念のため多めに」変更する**
ことが、合成リスクの注入に相当する——このケースの望ましくない性質は「関係が
存在するかどうか」ではなく「いくら委任するか」という金額の側にあるため
(incentive_engine.py冒頭の注記参照)。

シーン1(平常時): 各エージェントが、実際の用途に対して過不足のない金額を委任する。
  保有額は全員 intended_max_budget 以内に収まり、想定外の決済余地は生まれない。
シーン2(合成リスク注入): 既存の委任関係はそのまま、1件の委任額だけを
  「念のため多めに」変更する(単独では局所的に正当に見える判断)。この1件が
  下流のエージェントに、本来の用途を超える決済余地を生む。
シーン3(根本原因の特定、反実仮想): シーン2から注入した金額変更だけを元の値に
  戻した場合の保有額を計測し、「その1件を戻せば想定外の決済余地は消える」ことを
  示す(計測のみ、メカニズムの構成要素にはしない、CLAUDE.md 9章)。
"""
from __future__ import annotations

from dataclasses import dataclass

from aggregation import AggregationOutcome, TerminationConfig, run_mechanism
from environment import EnvironmentClient
from incentive_engine import PartialDelegationEngine
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import Trace
from schemas.incentive_schema import Declaration

from delegation_agents import BudgetDelegatingAgent


@dataclass
class SceneResult:
    name: str
    outcome: AggregationOutcome
    held: dict[str, float]
    declarations: list[Declaration]


@dataclass
class EscalationReport:
    scene2_escalated: list[str]
    scene2_held: dict[str, float]
    scene3_counterfactual_held: dict[str, float]
    root_cause_agent_id: str
    root_cause_confirmed: bool
    """シーン2で注入した1件の委任額変更を元に戻すと、想定外の決済余地が完全に消えるか。"""


def _collect_declarations(agents: list[Agent], env: EnvironmentClient, round_id: int) -> list[Declaration]:
    trace_summary = {"round": round_id, "history_size": len(env.read_traces())}
    declarations: list[Declaration] = []
    for agent in agents:
        action = agent.decide(ObservationInput(trace_summary=trace_summary))
        declarations.append(
            Declaration(agent_id=agent.agent_id, delegate_to=action.delegate_to, declared_value=action.declared_value)
        )
    return declarations


def run_scene(
    name: str,
    agents: list[Agent],
    engine: PartialDelegationEngine,
    env: EnvironmentClient,
    termination: TerminationConfig | None = None,
) -> SceneResult:
    """1シーン(1ラウンド)分: 委任宣言収集→保有額解決→集約実行→痕跡の書き込み。"""
    round_id = env.advance_round()
    declarations = _collect_declarations(agents, env, round_id)
    held = engine.resolve_reachable_budgets(declarations)
    outcome = run_mechanism(engine, declarations, termination=termination)
    for declaration in declarations:
        env.write_trace(
            writer_id=declaration.agent_id,
            trace=Trace(
                agent_id=declaration.agent_id,
                round_id=round_id,
                payload=declaration,
                process_trace={"held_budget": held.get(declaration.agent_id)},
            ),
        )
    return SceneResult(name=name, outcome=outcome, held=held, declarations=declarations)


def run_three_scene_demo(
    baseline_agents: list[Agent],
    injected_agent_id: str,
    injected_delegate_to: str | None,
    injected_declared_value: float,
    baseline_declared_value: float,
    engine: PartialDelegationEngine,
    env: EnvironmentClient,
    *,
    scene1_rounds: int = 3,
    scene2_rounds: int = 3,
    termination: TerminationConfig | None = None,
) -> tuple[list[SceneResult], EscalationReport]:
    """シーン1〜3を通しで実行する。baseline_agentsのうちinjected_agent_idの
    declared_value(delegate_toは変えない)のみを、シーン2でinjected_declared_valueに
    差し替える。シーン3の反実仮想はbaseline_declared_valueに戻して比較する。

    baseline_agentsはLeakDetectingAgent等のラッパーである可能性があるため、
    元のdeclared_valueをbaseline_agentsから読み取らず、呼び出し側に明示的に
    渡してもらう(ラッパーの内部実装に依存しない)。
    """
    results: list[SceneResult] = []
    for _ in range(scene1_rounds):
        results.append(run_scene("scene1_baseline", baseline_agents, engine, env, termination))

    injected_agents = [
        BudgetDelegatingAgent(a.agent_id, injected_delegate_to, injected_declared_value)
        if a.agent_id == injected_agent_id
        else a
        for a in baseline_agents
    ]
    for _ in range(scene2_rounds):
        results.append(run_scene("scene2_budget_injected", injected_agents, engine, env, termination))

    scene2_result = results[-1]
    scene2_escalated = sorted(scene2_result.outcome.result.allocated_agent_ids) if scene2_result.outcome.result else []

    # シーン3(計測): 注入した1件の金額変更だけを元に戻した場合(シーン1相当の宣言)の
    # 保有額を、メカニズムを介さず直接計算する(環境への書き込みは行わない、
    # CLAUDE.md 9章「反実仮想比較は計測・ログ出力として実装し、メカニズムの
    # 構成要素にしない」)。
    counterfactual_declarations = [
        Declaration(
            agent_id=d.agent_id,
            delegate_to=d.delegate_to,
            declared_value=(baseline_declared_value if d.agent_id == injected_agent_id else d.declared_value),
        )
        for d in scene2_result.declarations
    ]
    counterfactual_held = engine.resolve_reachable_budgets(counterfactual_declarations)
    root_cause_confirmed = all(
        counterfactual_held[agent_id] <= engine.parameters.intended_max_budget[agent_id] + 1e-9
        for agent_id in counterfactual_held
    )

    report = EscalationReport(
        scene2_escalated=scene2_escalated,
        scene2_held=scene2_result.held,
        scene3_counterfactual_held=counterfactual_held,
        root_cause_agent_id=injected_agent_id,
        root_cause_confirmed=root_cause_confirmed,
    )
    return results, report
