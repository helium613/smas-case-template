"""ケース3のラウンド進行をLangGraphで実装する(CLAUDE.md 7章)。

D-21/D-22で「次の課題」として持ち越したLangGraph状態プロキシパターン検証を、
D-27の方針どおりケース3で初めて実地検証する(介入ポートをケース2で消化した
のと同じ要領)。

必須チェックリスト(CLAUDE.md 7章)への対応:
1. Stateは①環境層への参照のみを持っているか
   → environment_ref(EnvironmentClient)は参照であり、蓄積された痕跡履歴
     (①環境層の内部状態、_traces)を複製しない。round_id/declarations/outcome
     は、非LangGraph版(cases/task_allocation/deviation_test.pyのrun_scene)
     におけるローカル変数に相当する、1ラウンド限りの使い捨ての中間値であり、
     次ラウンドに引き継がれる「データの実体」ではない。agents/engine/termination
     も同様に、実行に必要な参照・設定であって①環境層のデータではない。
2. 壁(アクセス制御)がフレームワークによって迂回されていないか
   → record_node は environment.EnvironmentClient.write_trace をそのまま
     呼ぶだけであり、writer_id=trace.agent_id の制約(壁の実体)は
     environment.py側でこれまでと同一のまま効く。LangGraphのノードが
     他エージェントの代わりに書き込むような経路は存在しない。
3. フレームワークのノード実行順序が②③⑤の役割に越境していないか
   → collect_rankings_node=④(申告収集のみ)、aggregate_node=③
     (run_mechanism経由で②を呼ぶだけ)、record_node=①(書き込みのみ)。
     ⑤検証層(DisCoPy構造検証)はこのグラフの外側(smoke_test/
     generate_results_summary)で独立に実行し、グラフのノードには含めない
     (検証層は横断的な事後チェックであり、実行パイプラインの一部ではない、D-21)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from aggregation import AggregationOutcome, TerminationConfig, run_mechanism
from environment import EnvironmentClient
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import Trace
from schemas.incentive_schema import Declaration, IncentiveEngine, ParticipationRecord


class VotingRoundState(TypedDict):
    environment_ref: EnvironmentClient
    agents: list[Agent]
    engine: IncentiveEngine
    termination: TerminationConfig | None
    round_id: int
    declarations: list[Declaration]
    outcome: AggregationOutcome | None


def collect_rankings_node(state: VotingRoundState) -> dict:
    """④実行主体層: 各エージェントに順位を申告させる(①環境層はラウンド進行・
    読み取りのみに使い、書き込みはしない)。"""
    env = state["environment_ref"]
    round_id = env.advance_round()
    trace_summary = {"round": round_id, "history_size": len(env.read_traces())}
    declarations: list[Declaration] = []
    for agent in state["agents"]:
        observation = ObservationInput(trace_summary=trace_summary)
        action = agent.decide(observation)
        declarations.append(
            Declaration(agent_id=agent.agent_id, declared_ranking=action.declared_ranking)
        )
    return {"round_id": round_id, "declarations": declarations}


def aggregate_node(state: VotingRoundState) -> dict:
    """③集約層: 共通実装のrun_mechanism経由で②誘因構造エンジンを呼ぶ。"""
    outcome = run_mechanism(state["engine"], state["declarations"], termination=state["termination"])
    return {"outcome": outcome}


def record_node(state: VotingRoundState) -> dict:
    """①環境層: 各エージェントが自領域にのみ参加記録を書き込む(壁はそのまま効く)。

    declared_ranking自体はParticipationRecordの型(スカラー値中心)に収まらない
    ため、Trace.process_trace(①環境層A側の任意拡張ポイント)に格納する
    (3ケースを通じて、この拡張ポイントが実際に使われる初めての例)。
    """
    env = state["environment_ref"]
    outcome = state["outcome"]
    winner = (
        outcome.result.allocated_agent_ids[0]
        if outcome.result and outcome.result.allocated_agent_ids
        else None
    )
    for declaration in state["declarations"]:
        preferred_winner = bool(declaration.declared_ranking) and declaration.declared_ranking[0] == winner
        record = ParticipationRecord(declared_value=0.0, won=preferred_winner, payment=0.0, eligible=True)
        env.write_trace(
            writer_id=declaration.agent_id,
            trace=Trace(
                agent_id=declaration.agent_id,
                round_id=state["round_id"],
                payload=record,
                process_trace={"declared_ranking": declaration.declared_ranking},
            ),
        )
    return {}


def build_voting_graph():
    graph = StateGraph(VotingRoundState)
    graph.add_node("collect_rankings", collect_rankings_node)
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("record", record_node)
    graph.add_edge(START, "collect_rankings")
    graph.add_edge("collect_rankings", "aggregate")
    graph.add_edge("aggregate", "record")
    graph.add_edge("record", END)
    return graph.compile()


@dataclass
class VotingSceneResult:
    name: str
    outcome: AggregationOutcome
    declarations: list[Declaration]


def run_voting_round(
    name: str,
    agents: list[Agent],
    engine: IncentiveEngine,
    env: EnvironmentClient,
    termination: TerminationConfig | None = None,
    compiled_graph=None,
) -> VotingSceneResult:
    """1ラウンド分をLangGraphで実行する(非LangGraph版のrun_sceneに相当)。"""
    app = compiled_graph or build_voting_graph()
    initial_state: VotingRoundState = {
        "environment_ref": env,
        "agents": agents,
        "engine": engine,
        "termination": termination,
        "round_id": 0,
        "declarations": [],
        "outcome": None,
    }
    final_state = app.invoke(initial_state)
    return VotingSceneResult(
        name=name, outcome=final_state["outcome"], declarations=final_state["declarations"]
    )
