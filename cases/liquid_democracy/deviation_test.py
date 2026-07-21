"""ケース4のシナリオ(3シーン構成)。

ケース1〜3の「1エージェントの逸脱・操作」という筋書きとは異なり、このケースの
主眼は**委任構造そのものが新しい問題を持ち込むか**にある(D-30)。

シーン1(平常時+忠実性の証明): 循環なしの委任チェーンで決定→「全員が忠実に
  委任した場合、委任なしで直接投票した場合と同じ結果になる」ことを検証する
  (評価観点#19「委任連鎖を通した誘因構造の伝播の妥当性」の、最も文字通りの
  解釈: 委任を経由しても各人の真の選好の反映=誘因構造が劣化しない、という
  一種の保存則)。
シーン2(循環委任の注入): 循環委任を意図的に作り、(a)解決が停止すること
  (打ち切り耐性#23と同じ思想を連鎖解決の粒度で適用)、(b)循環に含まれる
  票が正しく無効化されること、(c)他のエージェントの票に影響しないことを確認。
シーン3(スーパー代理人): 多数が1人に委任するケースを作り、重みが正しく
  集約されることを確認する(#14権力集中の不在の定義を問い直す素材、
  generate_results_summary.pyで論じる)。
"""
from __future__ import annotations

from dataclasses import dataclass

from aggregation import AggregationOutcome, TerminationConfig, run_mechanism
from environment import EnvironmentClient
from incentive_engine import LiquidDemocracyEngine
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import Trace
from schemas.incentive_schema import Declaration


@dataclass
class SceneResult:
    name: str
    outcome: AggregationOutcome
    resolved: dict[str, str | None]
    declarations: list[Declaration]


def _collect_declarations(agents: list[Agent], env: EnvironmentClient, round_id: int) -> list[Declaration]:
    trace_summary = {"round": round_id, "history_size": len(env.read_traces())}
    declarations: list[Declaration] = []
    for agent in agents:
        action = agent.decide(ObservationInput(trace_summary=trace_summary))
        declarations.append(
            Declaration(agent_id=agent.agent_id, declared_ranking=action.declared_ranking, delegate_to=action.delegate_to)
        )
    return declarations


def run_scene(
    name: str,
    agents: list[Agent],
    engine: LiquidDemocracyEngine,
    env: EnvironmentClient,
    termination: TerminationConfig | None = None,
) -> SceneResult:
    """1シーン(1ラウンド)分: 申告収集→委任解決→集約実行→参加記録の書き込み。"""
    round_id = env.advance_round()
    declarations = _collect_declarations(agents, env, round_id)
    resolved = engine.resolve_delegations(declarations)
    outcome = run_mechanism(engine, declarations, termination=termination)
    for declaration in declarations:
        env.write_trace(
            writer_id=declaration.agent_id,
            trace=Trace(
                agent_id=declaration.agent_id,
                round_id=round_id,
                payload=declaration,
                process_trace={"resolved_choice": resolved.get(declaration.agent_id)},
            ),
        )
    return SceneResult(name=name, outcome=outcome, resolved=resolved, declarations=declarations)


def weight_conservation_holds(resolved: dict[str, str | None], total_agents: int) -> bool:
    """重みの保存則: 有効票+無効票(循環等)の合計が、参加エージェント総数と一致するか。

    resolve_delegationsは全エージェントに対して必ず何らかの値(選択肢またはNone)を
    設定するため、これは構造的に常に成立するはずだが、検証として明示的に確認する。
    """
    return len(resolved) == total_agents


def faithfulness_holds(resolved: dict[str, str | None], true_preferences: dict[str, str], choices: list[str]) -> bool:
    """忠実性(#19): 全員が忠実に委任した場合、委任を経由した集計結果と、
    各人の真の選好をそのまま直接投票させた場合(反実仮想、委任なし)の
    集計結果が一致するか。"""
    delegated_tally = {c: 0 for c in choices}
    for choice in resolved.values():
        if choice in delegated_tally:
            delegated_tally[choice] += 1
    flat_tally = {c: 0 for c in choices}
    for pref in true_preferences.values():
        if pref in flat_tally:
            flat_tally[pref] += 1
    delegated_winner = max(choices, key=lambda c: delegated_tally[c])
    flat_winner = max(choices, key=lambda c: flat_tally[c])
    return delegated_winner == flat_winner
