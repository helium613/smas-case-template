"""①〜⑤の疎通確認スクリプト(疎通確認レベル、簡易スクラッチ実装のためpytest等は使わない)。

python cases/liquid_democracy/smoke_test.py で(リポジトリルートから)実行する。

ケース1〜3の「1エージェントの逸脱・操作」という筋書きとは異なり、このケースの
主眼は委任構造そのもの(循環委任・重みの保存則・権力集中の性質の違い)にある(D-30)。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aggregation import TerminationConfig, run_mechanism
from delegation_agents import DelegatingAgent, DirectVotingAgent
from deviation_test import faithfulness_holds, run_scene, weight_conservation_holds
from environment import EnvironmentClient, WallViolation
from incentive_engine import LiquidDemocracyEngine, LiquidDemocracyParameters
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration
from verification import run_structural_verification


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main() -> None:
    with open(Path(__file__).parent / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    params = LiquidDemocracyParameters(**config["mechanism"])
    engine = LiquidDemocracyEngine(params)
    termination = TerminationConfig(**config["aggregation"])
    env_config = EnvironmentConfig(**config["environment"])

    # --- ①環境層: 壁・減衰(共通実装、他ケースと同一の確認) ---------------------
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

    # --- ②誘因構造層: 委任解決(手計算で検証済みの基本シナリオ) --------------------
    basic_declarations = [
        Declaration(agent_id="alice", declared_ranking=["yes"]),
        Declaration(agent_id="bob", declared_ranking=["no"]),
        Declaration(agent_id="carol", delegate_to="alice"),
        Declaration(agent_id="dave", delegate_to="carol"),
    ]
    resolved = engine.resolve_delegations(basic_declarations)
    check(
        "②誘因構造層: 委任連鎖(dave→carol→alice)はaliceの選択(yes)まで正しく解決される",
        resolved == {"alice": "yes", "bob": "no", "carol": "yes", "dave": "yes"},
    )
    result = engine.allocate_and_pay(basic_declarations)
    check("②誘因構造層: 重み付き多数決でyesが勝つ(alice/carol/dave=3 vs bob=1)", result.allocated_agent_ids == ["yes"])

    cycle_declarations = [
        Declaration(agent_id="frank", delegate_to="grace"),
        Declaration(agent_id="grace", delegate_to="heidi"),
        Declaration(agent_id="heidi", delegate_to="frank"),
    ]
    cycle_resolved = engine.resolve_delegations(cycle_declarations)
    check(
        "②誘因構造層: 循環委任(frank→grace→heidi→frank)は全員無効票になる",
        cycle_resolved == {"frank": None, "grace": None, "heidi": None},
    )

    deep_chain = [Declaration(agent_id=f"agent{i}", delegate_to=f"agent{i+1}") for i in range(15)]
    deep_chain.append(Declaration(agent_id="agent15", declared_ranking=["yes"]))
    deep_resolved = engine.resolve_delegations(deep_chain)
    check(
        "②誘因構造層: 最大深さ(10)を超える連鎖は無効票になる(打ち切りルールと同じ思想)",
        deep_resolved["agent0"] is None,
    )

    # --- ③集約層: 打ち切りルール(共通実装、他ケースと同一の確認) -----------------
    outcome = run_mechanism(engine, basic_declarations, termination=termination)
    check("③集約層: 正常系ではフォールバックに落ちない", not outcome.terminated_by_fallback)

    # --- ④実行主体層: 直接投票 / 委任エージェント ---------------------------------
    from schemas.agent_schema import ObservationInput

    obs = ObservationInput(trace_summary={})
    check(
        "④実行主体層: 直接投票エージェントは真の選好どおりに申告する",
        DirectVotingAgent("alice", "yes").decide(obs).declared_ranking == ["yes"],
    )
    check(
        "④実行主体層: 委任エージェントは指定した委任先をそのまま申告する",
        DelegatingAgent("carol", "alice").decide(obs).delegate_to == "alice",
    )

    # --- ⑤検証層: DisCoPyによる合成則チェック(共通実装) --------------------------
    report = run_structural_verification(all_agent_ids=["alice", "bob", "carol", "dave"], write_own_domain_only=True)
    check("⑤検証層: 構造検証(結合律・単位律・境界の型一致)がすべてPassする", report.all_passed)

    # --- シーン1(平常時+忠実性の証明、#19) ----------------------------------------
    scene1_env = EnvironmentClient(env_config)
    scene1_agents = [
        DirectVotingAgent("alice", "yes"),
        DirectVotingAgent("bob", "no"),
        DelegatingAgent("carol", "alice"),
        DelegatingAgent("dave", "carol"),
        DelegatingAgent("erin", "bob"),
    ]
    scene1 = run_scene("scene1_faithful_delegation", scene1_agents, engine, scene1_env, termination)
    true_preferences = {"alice": "yes", "bob": "no", "carol": "yes", "dave": "yes", "erin": "no"}
    check(
        "シーン1: 重みの保存則(有効+無効の合計=参加者数)が成立する",
        weight_conservation_holds(scene1.resolved, total_agents=5),
    )
    check(
        "シーン1(#19): 全員が忠実に委任した場合、委任なしの直接投票と同じ結果になる(誘因構造の伝播が劣化しない)",
        faithfulness_holds(scene1.resolved, true_preferences, params.choices),
    )

    # --- シーン2(循環委任の注入) --------------------------------------------------
    scene2_env = EnvironmentClient(env_config)
    scene2_agents = [
        DirectVotingAgent("alice", "yes"),
        DirectVotingAgent("bob", "no"),
        DelegatingAgent("frank", "grace"),
        DelegatingAgent("grace", "heidi"),
        DelegatingAgent("heidi", "frank"),
    ]
    scene2 = run_scene("scene2_cycle_injected", scene2_agents, engine, scene2_env, termination)
    check(
        "シーン2: 循環委任の3者(frank/grace/heidi)は無効票になり、他者の票に影響しない",
        scene2.resolved["frank"] is None
        and scene2.resolved["grace"] is None
        and scene2.resolved["heidi"] is None
        and scene2.resolved["alice"] == "yes"
        and scene2.resolved["bob"] == "no",
    )
    check(
        "シーン2: 循環があっても解決は停止し(フォールバックに落ちない)、重みの保存則も成立する",
        not scene2.outcome.terminated_by_fallback and weight_conservation_holds(scene2.resolved, total_agents=5),
    )

    # --- シーン3(スーパー代理人、#14の再検討) --------------------------------------
    scene3_env = EnvironmentClient(env_config)
    scene3_agents = [
        DirectVotingAgent("priya", "yes"),
        DelegatingAgent("q1", "priya"),
        DelegatingAgent("q2", "priya"),
        DelegatingAgent("q3", "priya"),
        DelegatingAgent("q4", "priya"),
        DirectVotingAgent("r1", "no"),
    ]
    scene3 = run_scene("scene3_super_delegate", scene3_agents, engine, scene3_env, termination)
    priya_weight = sum(1 for choice in scene3.resolved.values() if choice == "yes")
    check(
        "シーン3: priyaに委任した4人+priya自身で、yesの重みが5に集約される",
        priya_weight == 5 and scene3.outcome.result.allocated_agent_ids == ["yes"],
    )
    check(
        "シーン3: 各委任は公開痕跡として監査可能(誰がpriyaに委任したかを他者が確認できる)",
        all(
            t.process_trace.get("resolved_choice") == "yes"
            for t in scene3_env.read_traces()
            if t.agent_id in {"q1", "q2", "q3", "q4"}
        ),
    )

    # --- 検証キット: モンテカルロ(構造的頑健性、循環を含むランダムな委任グラフ) -------
    rng = random.Random(0)
    n_trials = config["verification_kit"]["monte_carlo_trials"]
    agent_ids = [f"a{i}" for i in range(6)]
    conserved_count = 0
    had_cycle_count = 0
    for _ in range(n_trials):
        trial_declarations = []
        for agent_id in agent_ids:
            if rng.random() < 0.5:
                trial_declarations.append(Declaration(agent_id=agent_id, declared_ranking=[rng.choice(params.choices)]))
            else:
                target = rng.choice([a for a in agent_ids if a != agent_id])
                trial_declarations.append(Declaration(agent_id=agent_id, delegate_to=target))
        trial_resolved = engine.resolve_delegations(trial_declarations)
        if weight_conservation_holds(trial_resolved, total_agents=len(agent_ids)):
            conserved_count += 1
        if any(choice is None for choice in trial_resolved.values()):
            had_cycle_count += 1

    check(
        "検証キット: モンテカルロ全試行で重みの保存則が成立し、解決が例外なく停止する(循環を含む)",
        conserved_count == n_trials,
    )
    print(f"       (モンテカルロ N={n_trials}試行、循環等で無効票が出た試行数={had_cycle_count})")

    print("\nすべての疎通確認に成功しました。")


if __name__ == "__main__":
    main()
