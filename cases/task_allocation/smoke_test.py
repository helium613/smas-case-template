"""①〜⑤の疎通確認スクリプト(疎通確認レベル、簡易スクラッチ実装のためpytest等は使わない)。

python cases/task_allocation/smoke_test.py で(リポジトリルートから)実行する。
CLAUDE.md 9章の3シーン構成、5大指標の最小セットが、実際に動くことを確認する。

このファイルは cases/task_allocation/ 配下にあり、①③⑤等の共通実装(environment.py,
aggregation.py, verification.py, schemas/, agents/, verification_kit/)はリポジトリ
ルートに置かれている。common側をインポートできるよう、起動時にリポジトリルートを
sys.pathへ追加する(docs/DECISIONS.md D-23、cases/ディレクトリ導入の経緯)。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aggregation import TerminationConfig, aggregate_by_ranking, run_mechanism
from agents.llm_mock import ProbabilisticMockAgent
from agents.rule_based import (
    FluctuatingHonestAgent,
    GreedyOverstatingAgent,
    HonestRuleBasedAgent,
    OverstatingRuleBasedAgent,
)
from environment import EnvironmentClient, WallViolation
from incentive_engine import SingleItemVcgEngine, SingleItemVcgParameters
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration
from deviation_test import run_three_scene_demo
from verification import run_structural_verification
from verification_kit.gambit_collusion import check_pure_nash_collusion
from verification_kit.montecarlo import run_trials, summarize


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main() -> None:
    with open(Path(__file__).parent / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # --- ①環境層: 壁・減衰 -------------------------------------------------
    env_config = EnvironmentConfig(**config["environment"])
    env: EnvironmentClient = EnvironmentClient(env_config)
    env.advance_round()

    trace = Trace(agent_id="alice", round_id=env.current_round, payload=Declaration(agent_id="alice", declared_value=10.0))
    env.write_trace(writer_id="alice", trace=trace)
    check("①環境層: 自領域への書き込みが成功する", len(env.read_traces()) == 1)

    try:
        env.write_trace(writer_id="bob", trace=trace)
        wall_enforced = False
    except WallViolation:
        wall_enforced = True
    check("①環境層: 壁(他者領域への書き込み)が拒否される", wall_enforced)

    for _ in range(5):
        env.advance_round()
    weight = env.trace_weight(trace)
    check("①環境層: 減衰関数により重みが1.0未満に減衰する", 0.0 < weight < 1.0)

    # --- ②誘因構造層: サンプルのVCG(セカンドプライス)実装 ------------------
    engine = SingleItemVcgEngine(SingleItemVcgParameters(reserve_price=0.0))
    declarations = [
        Declaration(agent_id="alice", declared_value=10.0),
        Declaration(agent_id="bob", declared_value=7.0),
    ]
    result = engine.allocate_and_pay(declarations)
    check(
        "②誘因構造層: 最高申告者が資源を得て、2番目の価格を支払う",
        result.allocated_agent_ids == ["alice"] and result.payments["alice"] == 7.0,
    )

    # --- ③集約層: 打ち切りルール --------------------------------------------
    termination = TerminationConfig(**config["aggregation"])
    outcome = run_mechanism(engine, declarations, termination=termination)
    check("③集約層: 正常系ではフォールバックに落ちない", not outcome.terminated_by_fallback)

    class _FailingEngine:
        version = "x"
        parameters = None

        def allocate_and_pay(self, declarations):
            raise RuntimeError("常に失敗する(打ち切りルールのテスト用)")

    failing_outcome = run_mechanism(_FailingEngine(), declarations, termination=TerminationConfig(max_iterations=2, timeout_seconds=5.0))
    check("③集約層: エンジンが失敗し続けるとフォールバックに落ちる", failing_outcome.terminated_by_fallback)

    winner = aggregate_by_ranking(["alice", "bob", "carol"], [["alice", "bob", "carol"], ["bob", "alice", "carol"]])
    check("③集約層: pref_votingによる投票集約が動く", winner in {"alice", "bob"})

    # --- ④実行主体層: ルールベース / LLMモック ------------------------------
    honest = HonestRuleBasedAgent("alice", true_value=10.0)
    overstating = OverstatingRuleBasedAgent("alice", true_value=10.0, factor=1.3)
    from schemas.agent_schema import ObservationInput

    obs = ObservationInput(trace_summary={})
    check("④実行主体層: 正直エージェントは真の値を申告する", honest.decide(obs).declared_value == 10.0)
    check("④実行主体層: 過大申告エージェントは真の値より大きく申告する", overstating.decide(obs).declared_value > 10.0)

    mock = ProbabilisticMockAgent("alice", true_value=10.0, p_honest=0.0, rng=random.Random(0))
    check("④実行主体層: LLMモック(p_honest=0)は必ず逸脱する", mock.decide(obs).declared_value != 10.0)

    # --- ⑤検証層: DisCoPyによる合成則チェック --------------------------------
    report = run_structural_verification(all_agent_ids=["alice", "bob"], write_own_domain_only=True)
    check("⑤検証層: 構造検証(結合律・単位律・境界の型一致)がすべてPassする", report.all_passed)

    # --- 検証キット: モンテカルロ(③頑健性) ----------------------------------
    true_values = {"alice": 10.0, "bob": 7.0}

    def make_honest():
        return [Declaration(agent_id=a, declared_value=v) for a, v in true_values.items()]

    def deviate(decls: list[Declaration]) -> list[Declaration]:
        return [
            Declaration(agent_id=d.agent_id, declared_value=d.declared_value * 1.3 if d.agent_id == "alice" else d.declared_value)
            for d in decls
        ]

    trials = run_trials(engine, make_honest, deviate, true_values, target_agent_id="alice", n_trials=200)
    summary = summarize(trials)
    check(
        "検証キット: VCG(セカンドプライス)では過大申告が得にならない(耐戦略性)",
        summary["profitable_deviation_count"] == 0,
    )

    # --- 検証キット: pygambitによる結託耐性(#5、D-33で初めて使用) ------------------
    carol_true = 5.0

    def payoff(bid_alice: float, bid_bob: float) -> tuple[float, float]:
        decls = [
            Declaration(agent_id="alice", declared_value=bid_alice),
            Declaration(agent_id="bob", declared_value=bid_bob),
            Declaration(agent_id="carol", declared_value=carol_true),
        ]
        outcome = engine.allocate_and_pay(decls)

        def u(agent_id: str, true_value: float) -> float:
            if agent_id not in outcome.allocated_agent_ids:
                return 0.0
            return true_value - outcome.payments.get(agent_id, 0.0)

        return u("alice", true_values["alice"]), u("bob", true_values["bob"])

    collusion = check_pure_nash_collusion(
        strategies_a=[10.0, 12.0],
        strategies_b=[7.0, 0.0, 3.0],
        payoff_fn=payoff,
        honest_strategy_a=10.0,
        honest_strategy_b=7.0,
    )
    check(
        "検証キット(D-33): VCGは結託(bobが自分の申告を下げてaliceの支払いを圧縮する)に"
        "対して耐性がない(bobは非ピボット=自分の申告が勝敗を左右しないため無差別で、"
        "結託側の合計効用がより高い均衡が存在する。単独逸脱への耐戦略性とは別の脆弱性)",
        collusion.collusion_profitable,
    )

    # --- 3シーン構成の疎通確認(シーン3: 反実仮想比較による自己拘束の確認、D-07) ----
    scene_env: EnvironmentClient = EnvironmentClient(env_config)
    agent_ids = ["alice", "bob", "carol"]
    honest_agents = [
        FluctuatingHonestAgent(agent_id, index, n_agents=len(agent_ids))
        for index, agent_id in enumerate(agent_ids)
    ]

    def make_greedy_deviant(agent):
        return GreedyOverstatingAgent(agent.agent_id, fixed_declared_value=1000.0)

    scenes, report = run_three_scene_demo(
        honest_agents,
        deviating_agent_id="carol",
        deviating_agent_factory=make_greedy_deviant,
        engine=engine,
        env=scene_env,
        scene1_rounds=5,
        scene2_rounds=5,
    )
    scene_names = [s.name for s in scenes]
    check(
        "3シーン構成: scene1(x5)→scene2(x5)の順に実行され、シーン3は計測レポートとして得られる",
        scene_names == ["scene1_honest"] * 5 + ["scene2_deviation_injected"] * 5
        and len(report.rounds) == 5,
    )
    check(
        "3シーン構成: いずれのシーンもフォールバックに落ちずに完走する",
        all(not s.outcome.terminated_by_fallback for s in scenes),
    )

    scene2_results = [s for s in scenes if s.name == "scene2_deviation_injected"]
    carol_wins_in_scene2 = sum(1 for r in scene2_results if "carol" in r.outcome.result.allocated_agent_ids)
    check(
        "シーン2(逸脱注入): carolが固定高値の申告で当選を独占する",
        carol_wins_in_scene2 >= 3,
    )

    check(
        "シーン3(自己拘束): 逸脱の合計効用は、正直申告時(反実仮想)を上回らない(耐戦略性の直接実証)",
        not report.deviation_profitable,
    )
    check(
        "シーン3(自己拘束): 勝つべきでないラウンドで当選し、支払い超過で損をしたラウンドが存在する",
        any(r.actual_utility < r.counterfactual_utility for r in report.rounds),
    )
    print(
        f"       (carol 合計効用: 逸脱={report.total_actual_utility:+.1f} / "
        f"正直(反実仮想)={report.total_counterfactual_utility:+.1f})"
    )

    # --- 信用ゲート(2ケース目プレビュー、D-07/D-15): 純関数としての最小動作確認のみ ----
    # デモ本編(3シーン)からは外した。scene_env にはシーン2でcarolが当選を独占した
    # 公開痕跡が残っているため、ゲート関数が当選率の異常を機械的に検出できることだけ確認する。
    from incentive_engine import filter_eligible_declarations

    gate_input = [Declaration(agent_id=a, declared_value=1.0) for a in agent_ids]
    gated = filter_eligible_declarations(scene_env, gate_input)
    check(
        "(2ケース目プレビュー)信用ゲートは、当選率が異常な主体を公開痕跡から機械的に検出できる",
        all(d.agent_id != "carol" for d in gated) and len(gated) == 2,
    )

    print("\nすべての疎通確認に成功しました。")


if __name__ == "__main__":
    main()
