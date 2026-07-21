"""①〜⑤の疎通確認スクリプト(疎通確認レベル、簡易スクラッチ実装のためpytest等は使わない)。

python cases/proposal_voting/smoke_test.py で(リポジトリルートから)実行する。

ケース1・2と異なり、このケース(ボルダ得点、mechanism_catalog.md ファミリー2)
は意図的に非耐戦略性メカニズムを実装している(D-27)。そのため③頑健性・シーン2の
アサーションは「逸脱が得にならない」ではなく「逸脱が得になる具体例を実際に作れる」
ことを確認する形になる。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aggregation import TerminationConfig
from environment import EnvironmentClient, WallViolation
from incentive_engine import BordaVotingEngine, BordaVotingParameters
from langgraph_flow import build_voting_graph, run_voting_round
from schemas.agent_schema import ObservationInput
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration
from voting_agents import BuryingStrategicAgent, HonestVotingAgent
from deviation_test import run_two_scene_demo
from verification import run_structural_verification


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main() -> None:
    with open(Path(__file__).parent / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    candidate_ids = config["mechanism"]["candidate_ids"]
    termination = TerminationConfig(**config["aggregation"])
    engine = BordaVotingEngine(BordaVotingParameters(candidate_ids=candidate_ids))

    # --- ①環境層: 壁・減衰(共通実装、他ケースと同一の確認) ---------------------
    env_config = EnvironmentConfig(**config["environment"])
    env = EnvironmentClient(env_config)
    env.advance_round()

    trace = Trace(agent_id="alice", round_id=env.current_round, payload=Declaration(agent_id="alice"))
    env.write_trace(writer_id="alice", trace=trace)
    check("①環境層: 自領域への書き込みが成功する", len(env.read_traces()) == 1)

    try:
        env.write_trace(writer_id="bob", trace=trace)
        wall_enforced = False
    except WallViolation:
        wall_enforced = True
    check("①環境層: 壁(他者領域への書き込み)が拒否される", wall_enforced)

    # --- ②誘因構造層: ボルダ得点(手計算で検証済みの操作可能シナリオ、4候補) -------
    proposal_a, proposal_b, proposal_c, proposal_d = candidate_ids
    alice_true = {proposal_a: 10.0, proposal_b: 6.0, proposal_c: 3.0, proposal_d: 1.0}
    carol_true = {proposal_a: 9.0, proposal_b: 5.0, proposal_c: 2.0, proposal_d: 1.0}
    bob_true = {proposal_b: 10.0, proposal_a: 6.0, proposal_d: 4.0, proposal_c: 1.0}

    honest_declarations = [
        Declaration(agent_id="alice", declared_ranking=HonestVotingAgent("alice", alice_true).true_ranking()),
        Declaration(agent_id="carol", declared_ranking=HonestVotingAgent("carol", carol_true).true_ranking()),
        Declaration(agent_id="bob", declared_ranking=HonestVotingAgent("bob", bob_true).true_ranking()),
    ]
    honest_result = engine.allocate_and_pay(honest_declarations)
    check(
        "②誘因構造層: 全員正直申告なら真の1位選好が一致する候補(proposal_a)が採用される",
        honest_result.allocated_agent_ids == [proposal_a],
    )

    manipulated_ranking = BuryingStrategicAgent("bob", bob_true).manipulated_ranking()
    check(
        "②誘因構造層: 埋葬戦術は真の1位を維持し、真の2位を最下位に落とす",
        manipulated_ranking[0] == proposal_b and manipulated_ranking[-1] == proposal_a,
    )
    manipulated_declarations = [
        honest_declarations[0],
        honest_declarations[1],
        Declaration(agent_id="bob", declared_ranking=manipulated_ranking),
    ]
    manipulated_result = engine.allocate_and_pay(manipulated_declarations)
    check(
        "②誘因構造層: ボルダ得点は非耐戦略性(埋葬戦術でbobの真の1位=proposal_bが勝つ)",
        manipulated_result.allocated_agent_ids == [proposal_b],
    )

    # --- ③集約層: 打ち切りルール(共通実装、他ケースと同一の確認) -----------------
    from aggregation import run_mechanism

    outcome = run_mechanism(engine, honest_declarations, termination=termination)
    check("③集約層: 正常系ではフォールバックに落ちない", not outcome.terminated_by_fallback)

    class _FailingEngine:
        version = "x"
        parameters = None

        def allocate_and_pay(self, declarations):
            raise RuntimeError("常に失敗する(打ち切りルールのテスト用)")

    failing_outcome = run_mechanism(
        _FailingEngine(), honest_declarations, termination=TerminationConfig(max_iterations=2, timeout_seconds=5.0)
    )
    check("③集約層: エンジンが失敗し続けるとフォールバックに落ちる", failing_outcome.terminated_by_fallback)

    # --- ④実行主体層: 正直エージェント / 埋葬戦術エージェント ---------------------
    obs = ObservationInput(trace_summary={})
    honest_agent = HonestVotingAgent("bob", bob_true)
    check(
        "④実行主体層: 正直エージェントは真の評価額の降順どおりに申告する",
        honest_agent.decide(obs).declared_ranking == [proposal_b, proposal_a, proposal_d, proposal_c],
    )
    strategic_agent = BuryingStrategicAgent("bob", bob_true)
    check(
        "④実行主体層: 埋葬戦術エージェントは真の1位を維持し2位を最下位に落として申告する",
        strategic_agent.decide(obs).declared_ranking == [proposal_b, proposal_d, proposal_c, proposal_a],
    )

    # --- ⑤検証層: DisCoPyによる合成則チェック(共通実装) --------------------------
    report = run_structural_verification(all_agent_ids=["alice", "bob", "carol"], write_own_domain_only=True)
    check("⑤検証層: 構造検証(結合律・単位律・境界の型一致)がすべてPassする", report.all_passed)

    # --- フレームワーク統合: LangGraph状態プロキシパターン(CLAUDE.md 7章) ---------
    graph_env = EnvironmentClient(env_config)
    graph_agents = [
        HonestVotingAgent("alice", alice_true),
        HonestVotingAgent("carol", carol_true),
        HonestVotingAgent("bob", bob_true),
    ]
    compiled = build_voting_graph()
    scene = run_voting_round("scene_langgraph_check", graph_agents, engine, graph_env, termination, compiled)
    check(
        "LangGraph: グラフ経由の1ラウンド実行でも同じ勝者(proposal_a)が決まる",
        scene.outcome.result.allocated_agent_ids == [proposal_a],
    )
    check(
        "LangGraph: ①環境層への書き込みは各エージェントの自領域のみ(壁が迂回されていない)",
        len(graph_env.read_traces()) == 3
        and all(t.agent_id in {"alice", "bob", "carol"} for t in graph_env.read_traces()),
    )
    written_ranking = next(t.process_trace["declared_ranking"] for t in graph_env.read_traces() if t.agent_id == "bob")
    check(
        "LangGraph: process_trace拡張ポイントに申告ランキングが記録される",
        written_ranking == honest_agent.true_ranking(),
    )

    # --- 2シーン構成の疎通確認(シーン2: 埋葬戦術は理論どおり得になりうる、D-27) -----
    scene_env = EnvironmentClient(env_config)
    honest_scene_agents = [
        HonestVotingAgent("alice", alice_true),
        HonestVotingAgent("carol", carol_true),
        HonestVotingAgent("bob", bob_true),
    ]

    def make_burying(agent):
        return BuryingStrategicAgent(agent.agent_id, bob_true)

    scenes, manipulation_report = run_two_scene_demo(
        honest_scene_agents,
        manipulating_agent_id="bob",
        manipulating_agent_factory=make_burying,
        manipulating_agent_true_values=bob_true,
        engine=engine,
        env=scene_env,
        scene1_rounds=5,
        scene2_rounds=5,
    )
    scene_names = [s.name for s in scenes]
    check(
        "2シーン構成: scene1(x5)→scene2(x5)の順に実行され、シーン2は計測レポートとして得られる",
        scene_names == ["scene1_honest"] * 5 + ["scene2_manipulation_injected"] * 5
        and len(manipulation_report.rounds) == 5,
    )
    check(
        "シーン2: 埋葬戦術は理論どおり得になる(耐戦略性を満たさない設計の実証、意図的な結果)",
        manipulation_report.manipulation_profitable,
    )
    print(
        f"       (bob 合計効用: 埋葬戦術={manipulation_report.total_actual_utility:+.1f} / "
        f"正直(反実仮想)={manipulation_report.total_counterfactual_utility:+.1f})"
    )

    # --- 検証キット: モンテカルロ(③頑健性、ここでは"検出できるか"の確認) -----------
    rng = random.Random(0)
    n_trials = min(config["verification_kit"]["monte_carlo_trials"], 200)
    profitable = 0
    for _ in range(n_trials):
        a_true = {c: rng.uniform(1.0, 10.0) for c in candidate_ids}
        c_true = {c: rng.uniform(1.0, 10.0) for c in candidate_ids}
        b_true = {c: rng.uniform(1.0, 10.0) for c in candidate_ids}
        trial_honest = [
            Declaration(agent_id="alice", declared_ranking=HonestVotingAgent("alice", a_true).true_ranking()),
            Declaration(agent_id="carol", declared_ranking=HonestVotingAgent("carol", c_true).true_ranking()),
            Declaration(agent_id="bob", declared_ranking=HonestVotingAgent("bob", b_true).true_ranking()),
        ]
        honest_r = engine.allocate_and_pay(trial_honest)
        honest_u = honest_r.allocated_agent_ids[0]

        trial_manipulated = [
            trial_honest[0],
            trial_honest[1],
            Declaration(agent_id="bob", declared_ranking=BuryingStrategicAgent("bob", b_true).manipulated_ranking()),
        ]
        manipulated_r = engine.allocate_and_pay(trial_manipulated)
        manipulated_u = manipulated_r.allocated_agent_ids[0]

        if b_true.get(manipulated_u, 0.0) > b_true.get(honest_u, 0.0):
            profitable += 1

    check(
        "検証キット: モンテカルロで埋葬戦術が得になる試行が一定割合存在する(非耐戦略性の経験的確認)",
        profitable > 0,
    )
    print(f"       (モンテカルロ N={n_trials}試行中、埋葬戦術が得になった試行数={profitable})")

    print("\nすべての疎通確認に成功しました。")


if __name__ == "__main__":
    main()
