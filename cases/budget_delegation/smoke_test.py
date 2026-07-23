"""①〜⑤の疎通確認スクリプト(疎通確認レベル、簡易スクラッチ実装のためpytest等は使わない)。

python cases/budget_delegation/smoke_test.py で(リポジトリルートから)実行する。

ケース5(IAM委任チェーン)と同じく、このケースの主眼も「誰も虚偽申告していない
のに、複数の個別には正当な委任判断が合成されることで、誰も意図しない決済余地
が生まれるか」(confused deputy)にある。ただしケース5がtierの完全継承
(MAX集約・保存則なし)だったのに対し、このケースは金額の部分譲渡(SUM集約・
委任元の保有額を上限とする制約あり)という異なる数理構造を持つ。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from environment import EnvironmentClient, WallViolation
from incentive_engine import PartialDelegationEngine, PartialDelegationParameters
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration
from verification import run_structural_verification
from verification_kit.information_asymmetry import LeakDetectingAgent, no_intra_round_leak, total_checks

from delegation_agents import BudgetDelegatingAgent
from deviation_test import run_three_scene_demo


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main() -> None:
    with open(Path(__file__).parent / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    params = PartialDelegationParameters(**config["mechanism"])
    engine = PartialDelegationEngine(params)
    env_config = EnvironmentConfig(**config["environment"])

    # --- ①環境層: 壁(共通実装、他ケースと同一の確認) --------------------------
    env = EnvironmentClient(env_config)
    env.advance_round()
    trace = Trace(agent_id="me", round_id=env.current_round, payload=Declaration(agent_id="me"))
    env.write_trace(writer_id="me", trace=trace)
    check("①環境層: 自領域への書き込みが成功する", len(env.read_traces()) == 1)
    try:
        env.write_trace(writer_id="booking", trace=trace)
        wall_enforced = False
    except WallViolation:
        wall_enforced = True
    check("①環境層: 壁(他者領域への書き込み)が拒否される", wall_enforced)

    # --- ②誘因構造層: 平常時の委任チェーン(手計算で検証済み) ---------------------
    # me(50000円)→booking(45000円、実際の用途どおり)→transport(2000円、実際の
    # 用途どおり)。dining は誰からも委任されない対照エージェント。
    basic_declarations = [
        Declaration(agent_id="me", delegate_to="booking", declared_value=45000.0),
        Declaration(agent_id="booking", delegate_to="transport", declared_value=2000.0),
        Declaration(agent_id="transport"),
        Declaration(agent_id="dining"),
    ]
    held = engine.resolve_reachable_budgets(basic_declarations)
    check(
        "②誘因構造層: bookingは委任どおり45000円を保有する",
        held["booking"] == 45000.0,
    )
    check(
        "②誘因構造層: transportは委任どおり2000円を保有する",
        held["transport"] == 2000.0,
    )
    outcome = engine.allocate_and_pay(basic_declarations)
    check("②誘因構造層: 平常時の委任構成では想定外の決済余地が発生しない", outcome.allocated_agent_ids == [])

    # --- ②誘因構造層: 委任元の保有額を超える委任はできない(実額ならではの制約) -----
    over_declared = [
        Declaration(agent_id="me", delegate_to="booking", declared_value=45000.0),
        Declaration(agent_id="booking", delegate_to="transport", declared_value=999999.0),
        Declaration(agent_id="transport"),
        Declaration(agent_id="dining"),
    ]
    over_held = engine.resolve_reachable_budgets(over_declared)
    check(
        "②誘因構造層: bookingが自分の保有額(45000円)を超えて委任しようとしても、"
        "transportが実際に受け取れるのはmin(宣言額, 保有額)=45000円に制約される",
        over_held["transport"] == 45000.0,
    )

    # --- ②誘因構造層: 循環委任(相互委任)でもクラッシュせず、有限値に収束する -------
    cycle_params = PartialDelegationParameters(
        root_budgets={"x": 100.0, "y": 0.0},
        intended_max_budget={"x": 100.0, "y": 60.0},
        max_chain_depth=10,
    )
    cycle_engine = PartialDelegationEngine(cycle_params)
    cycle_declarations = [
        Declaration(agent_id="x", delegate_to="y", declared_value=60.0),
        Declaration(agent_id="y", delegate_to="x", declared_value=20.0),
    ]
    cycle_held = cycle_engine.resolve_reachable_budgets(cycle_declarations)
    check(
        "②誘因構造層: 循環委任(xとyが相互に一部を委任)でも無限ループにならず有限値に収束する",
        cycle_held == {"x": 120.0, "y": 60.0},
    )
    check(
        "②誘因構造層(発見): 循環委任の「キックバック」により、xの保有額(120)が"
        "x自身のintended_max_budget(100)を超える(xは誰からも虚偽の金額を"
        "受け取っていないのに、相互委任の合成だけで自分の本来の上限を超えてしまう)",
        cycle_engine.allocate_and_pay(cycle_declarations).allocated_agent_ids == ["x"],
    )

    # --- ⑤検証層: DisCoPyによる合成則チェック(共通実装) ------------------------------
    report = run_structural_verification(
        all_agent_ids=["me", "booking", "transport", "dining"],
        write_own_domain_only=True,
    )
    check("⑤検証層: 構造検証(結合律・単位律・境界の型一致)がすべてPassする", report.all_passed)

    # --- 3シーン構成: 平常時→合成リスク注入(金額変更)→根本原因の特定(反実仮想) --------
    scene_env = EnvironmentClient(env_config)
    baseline_agents = [
        BudgetDelegatingAgent("me", "booking", 45000.0),
        BudgetDelegatingAgent("booking", "transport", 2000.0),
        BudgetDelegatingAgent("transport", None),
        BudgetDelegatingAgent("dining", None),
    ]
    leak_agents = [LeakDetectingAgent(a, scene_env) for a in baseline_agents]

    scenes, esc_report = run_three_scene_demo(
        leak_agents,
        injected_agent_id="booking",
        injected_delegate_to="transport",
        injected_declared_value=10000.0,
        baseline_declared_value=2000.0,
        engine=engine,
        env=scene_env,
        scene1_rounds=3,
        scene2_rounds=3,
    )
    scene_names = [s.name for s in scenes]
    check(
        "3シーン構成: scene1(x3)→scene2(x3)の順に実行され、シーン3は計測レポートとして得られる",
        scene_names == ["scene1_baseline"] * 3 + ["scene2_budget_injected"] * 3,
    )
    check(
        "シーン1: 平常時は誰にも想定外の決済余地が生まれない",
        all(s.outcome.result.allocated_agent_ids == [] for s in scenes if s.name == "scene1_baseline"),
    )
    check(
        "シーン2: bookingの委任額変更(transportへの2000円→10000円、単独では"
        "「念のため」局所的に正当に見える判断)により、transportが本来の用途"
        "(2000円)を大きく超える決済余地(10000円)を持ってしまう"
        "(誰も虚偽申告していない)",
        set(esc_report.scene2_escalated) == {"transport"},
    )
    print(
        f"       (シーン2保有額: {esc_report.scene2_held}、"
        f"想定外の決済余地を持ったエージェント: {esc_report.scene2_escalated})"
    )
    check(
        "シーン3(根本原因の特定、反実仮想): 注入した委任額変更(booking→transport"
        "の10000円)だけを元の2000円に戻すと、想定外の決済余地は完全に消える",
        esc_report.root_cause_confirmed,
    )

    # --- 情報の非対称性の制御(#3、D-59の横展開) -------------------------------------
    check(
        f"3シーン構成(#3、情報の非対称性の制御): 全{total_checks(leak_agents)}回の"
        "意思決定タイミングで、同一ラウンド内の他者の委任宣言が一度も見えていない",
        no_intra_round_leak(leak_agents),
    )

    print("すべての疎通確認に成功しました。")


if __name__ == "__main__":
    main()
