"""①〜⑤の疎通確認スクリプト(ケース2: 信用枠配分)。

python cases/credit_allocation/smoke_test.py で(リポジトリルートから)実行する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))
sys.path.insert(0, str(_CASE_DIR))

from aggregation import run_mechanism
from agents.rule_based import GreedyOverstatingAgent
from environment import EnvironmentClient, WallViolation
from schemas.agent_schema import ObservationInput
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration
from verification import run_structural_verification

from credit_agents import CreditAwareHonestAgent, CreditLimitMaximizingAgent
from deviation_test import run_four_scene_demo, run_sustained_strategy_comparison
from incentive_engine import TriggerStrategyEngine, TriggerStrategyParameters, compute_credit_limit
from payloads import CreditRoundRecord


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env_config = EnvironmentConfig(**config["environment"])
    params = TriggerStrategyParameters(**config["mechanism"])
    scenario = config["scenario"]

    # --- ①環境層: 壁・減衰(共通実装、ケース1と同じ性質を再確認) ------------------
    env = EnvironmentClient(env_config)
    env.advance_round()
    trace = Trace(
        agent_id="alice",
        round_id=env.current_round,
        payload=CreditRoundRecord(declared_value=5.0, credit_limit_at_declaration=10.0, won=True, compliant=True),
    )
    env.write_trace(writer_id="alice", trace=trace)
    check("①環境層: 自領域への書き込みが成功する", len(env.read_traces()) == 1)
    try:
        env.write_trace(writer_id="bob", trace=trace)
        wall_enforced = False
    except WallViolation:
        wall_enforced = True
    check("①環境層: 壁(他者領域への書き込み)が拒否される", wall_enforced)

    # --- ②誘因構造層: 配分ルール(最高申告額が勝つ、支払いなし) ---------------------
    engine = TriggerStrategyEngine(params)
    declarations = [
        Declaration(agent_id="alice", declared_value=10.0),
        Declaration(agent_id="bob", declared_value=7.0),
    ]
    result = engine.allocate_and_pay(declarations)
    check(
        "②誘因構造層: 最高申告者が資源を得て、支払いは発生しない",
        result.allocated_agent_ids == ["alice"] and result.payments == {},
    )

    # --- ②誘因構造層: 信用枠の導出(違反→制裁、遵守→拡大) --------------------------
    credit_env = EnvironmentClient(env_config)
    r1 = credit_env.advance_round()
    limit_before_history = compute_credit_limit(credit_env, "carol", r1, params)
    check("②誘因構造層: 履歴が無いエージェントはbase_limitから始まる", limit_before_history.credit_limit == params.base_limit)

    credit_env.write_trace(
        writer_id="carol",
        trace=Trace(
            agent_id="carol", round_id=r1,
            payload=CreditRoundRecord(declared_value=999.0, credit_limit_at_declaration=params.base_limit, won=True, compliant=False),
        ),
    )
    r2 = credit_env.advance_round()
    limit_after_violation = compute_credit_limit(credit_env, "carol", r2, params)
    check(
        "②誘因構造層: 違反直後は信用枠が制裁水準まで縮小する",
        limit_after_violation.in_punishment and limit_after_violation.credit_limit == params.punishment_limit,
    )

    for round_offset in range(params.punishment_rounds):
        credit_env.write_trace(
            writer_id="carol",
            trace=Trace(
                agent_id="carol", round_id=credit_env.current_round,
                payload=CreditRoundRecord(declared_value=0.5, credit_limit_at_declaration=params.punishment_limit, won=False, compliant=True),
            ),
        )
        credit_env.advance_round()
    limit_after_recovery_start = compute_credit_limit(credit_env, "carol", credit_env.current_round, params)
    check(
        "②誘因構造層: 制裁期間が明けると信用枠の回復(拡大)が始まる",
        not limit_after_recovery_start.in_punishment and limit_after_recovery_start.credit_limit > params.punishment_limit,
    )

    # --- ③集約層: 打ち切りルール(共通実装) ------------------------------------------
    outcome = run_mechanism(engine, declarations)
    check("③集約層: 正常系ではフォールバックに落ちない", not outcome.terminated_by_fallback)

    # --- ④実行主体層: 信用枠を意識するエージェント / 常に無視するエージェント ----------
    honest = CreditAwareHonestAgent("alice", agent_index=0, n_agents=1, high_value=15.0, low_value=15.0)
    obs_with_limit = ObservationInput(trace_summary={"round": 0, "credit_limit": 10.0})
    check(
        "④実行主体層: 信用枠を意識するエージェントは、真の評価額が信用枠を超えたら信用枠に自己制限する",
        honest.decide(obs_with_limit).declared_value == 10.0,
    )
    greedy = GreedyOverstatingAgent("bob", fixed_declared_value=1000.0)
    check(
        "④実行主体層: 常に無視するエージェント(共通実装を再利用)は信用枠を無視する",
        greedy.decide(obs_with_limit).declared_value == 1000.0,
    )

    # --- ⑤検証層: DisCoPyによる合成則チェック(共通実装) ------------------------------
    report = run_structural_verification(all_agent_ids=["alice", "bob"], write_own_domain_only=True)
    check("⑤検証層: 構造検証(結合律・単位律・境界の型一致)がすべてPassする", report.all_passed)

    # --- 4シーン構成の疎通確認 -------------------------------------------------------
    agent_ids = ["alice", "bob", "carol"]

    def make_env() -> EnvironmentClient:
        return EnvironmentClient(env_config)

    demo_engine = TriggerStrategyEngine(params)
    results, comparison = run_four_scene_demo(
        agent_ids,
        deviating_agent_id="carol",
        engine=demo_engine,
        env_factory=make_env,
        build_rounds=scenario["build_rounds"],
        deviate_rounds=scenario["deviate_rounds"],
        punishment_rounds=scenario["punishment_rounds"],
        recover_rounds=scenario["recover_rounds"],
        discount=scenario["discount"],
    )
    check(
        "4シーン構成: 想定ラウンド数どおりに実行される",
        len(results)
        == scenario["build_rounds"] + scenario["deviate_rounds"] + scenario["punishment_rounds"] + scenario["recover_rounds"],
    )
    check(
        "4シーン構成: いずれのラウンドもフォールバックに落ちずに完走する",
        all(not r.terminated_by_fallback for r in results),
    )

    scene2 = [r for r in results if r.name == "scene2_deviation_injected"]
    check(
        "シーン2(逸脱注入): carolが信用枠を無視して当選する",
        any(r.outcome is not None and "carol" in r.outcome.allocated_agent_ids for r in scene2),
    )
    check(
        "シーン2(逸脱注入): carolの違反が記録される",
        any(not r.compliance["carol"] for r in scene2),
    )

    scene3 = [r for r in results if r.name == "scene3_trigger_active"]
    check(
        "シーン3(トリガー発動): carolの信用枠が制裁水準まで縮小している",
        all(r.credit_limits["carol"].in_punishment for r in scene3),
    )

    scene4 = [r for r in results if r.name == "scene4_recovery"]
    check(
        "シーン4(回復): 制裁期間を過ぎるとcarolの信用枠が回復し始める",
        scene4[-1].credit_limits["carol"].credit_limit > params.punishment_limit,
    )

    check(
        "4シーン構成: 逸脱の割引後合計効用は、遵守を貫いた場合(反実仮想)を上回らない",
        not comparison.deviation_profitable,
    )
    print(
        f"       (carol 割引後合計効用: 逸脱={comparison.actual_utility:+.2f} / "
        f"遵守を貫いた場合(反実仮想)={comparison.counterfactual_utility:+.2f})"
    )

    # --- D-37/D-38: 信用枠内に留まる恒常的な過大申告(素朴な逸脱とは異なる、検出されない戦略) ---
    sustained_comparison = run_sustained_strategy_comparison(
        agent_ids, "carol", lambda agent_id: CreditLimitMaximizingAgent(agent_id),
        demo_engine, lambda: EnvironmentClient(env_config), n_rounds=30, discount=0.9,
    )
    check(
        "D-37/D-38: 信用枠のすぐ下を狙う恒常的な過大申告は、GreedyOverstatingAgentとは異なり"
        "一切検出されず、honestを上回る(メカニズムファミリーに内在する既知の限界)",
        sustained_comparison.strategy_profitable,
    )
    print(
        f"       (carol 割引後合計効用: 信用枠内過大申告={sustained_comparison.strategy_utility:+.2f} / "
        f"honest={sustained_comparison.honest_utility:+.2f})"
    )

    print("\nすべての疎通確認に成功しました。")


if __name__ == "__main__":
    main()
