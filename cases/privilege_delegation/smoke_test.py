"""①〜⑤の疎通確認スクリプト(疎通確認レベル、簡易スクラッチ実装のためpytest等は使わない)。

python cases/privilege_delegation/smoke_test.py で(リポジトリルートから)実行する。

ケース1〜4の「1エージェントの逸脱・操作」という筋書きとは異なり、このケースの
主眼は「誰も虚偽申告していないのに、複数の個別には正当なtrust宣言が合成される
ことで、誰も意図しない権限昇格経路が生まれるか」(confused deputy)にある。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from environment import EnvironmentClient, WallViolation
from incentive_engine import PrivilegeDelegationEngine, PrivilegeDelegationParameters
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration
from verification import run_structural_verification
from verification_kit.information_asymmetry import LeakDetectingAgent, no_intra_round_leak, total_checks

from analysis import rank_chokepoint_edges, scan_candidate_trust_grants
from delegation_agents import TrustDeclaringAgent
from deviation_test import run_scene, run_three_scene_demo


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main() -> None:
    with open(Path(__file__).parent / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    params = PrivilegeDelegationParameters(**config["mechanism"])
    engine = PrivilegeDelegationEngine(params)
    env_config = EnvironmentConfig(**config["environment"])

    # --- ①環境層: 壁(共通実装、他ケースと同一の確認) --------------------------
    env = EnvironmentClient(env_config)
    env.advance_round()
    trace = Trace(agent_id="admin", round_id=env.current_round, payload=Declaration(agent_id="admin"))
    env.write_trace(writer_id="admin", trace=trace)
    check("①環境層: 自領域への書き込みが成功する", len(env.read_traces()) == 1)
    try:
        env.write_trace(writer_id="ci_svc", trace=trace)
        wall_enforced = False
    except WallViolation:
        wall_enforced = True
    check("①環境層: 壁(他者領域への書き込み)が拒否される", wall_enforced)

    # --- ②誘因構造層: 到達可能性の基本シナリオ(手計算で検証済み) -------------------
    # build_svcがci_svc経由でdeploy_svcまで到達するのは設計上正当(intended_max_tier=2)。
    basic_declarations = [
        Declaration(agent_id="admin"),
        Declaration(agent_id="deploy_svc", delegate_to="ci_svc"),
        Declaration(agent_id="ci_svc", delegate_to="build_svc"),
        Declaration(agent_id="build_svc"),
        Declaration(agent_id="intern_svc"),
    ]
    reachable = engine.resolve_reachable_tiers(basic_declarations)
    check(
        "②誘因構造層: build_svcはci_svc経由でdeploy_svcまで到達する(意図された2ホップ)",
        reachable["build_svc"] == 2,
    )
    outcome = engine.allocate_and_pay(basic_declarations)
    check("②誘因構造層: 平常時の信頼構成では権限昇格が発生しない", outcome.allocated_agent_ids == [])

    # --- ②誘因構造層: 循環trust(相互信頼)でもクラッシュしない --------------------
    cycle_params = PrivilegeDelegationParameters(
        tiers={"x": 1, "y": 2}, intended_max_tier={"x": 1, "y": 2}, max_chain_depth=5
    )
    cycle_engine = PrivilegeDelegationEngine(cycle_params)
    cycle_declarations = [
        Declaration(agent_id="x", delegate_to="y"),
        Declaration(agent_id="y", delegate_to="x"),
    ]
    cycle_reachable = cycle_engine.resolve_reachable_tiers(cycle_declarations)
    check(
        "②誘因構造層: 循環trust(xとyが相互に信頼)でも無限ループにならず、両者とも互いのtierに到達する",
        cycle_reachable == {"x": 2, "y": 2},
    )

    # --- ②誘因構造層: 打ち切りルール(max_chain_depth、CLAUDE.md 8章) ---------------
    depth_params = PrivilegeDelegationParameters(
        tiers={"n0": 0, "n1": 0, "n2": 0, "n3": 0, "n4": 9},
        intended_max_tier={"n0": 0, "n1": 0, "n2": 0, "n3": 0, "n4": 9},
        max_chain_depth=2,
    )
    depth_engine = PrivilegeDelegationEngine(depth_params)
    chain_declarations = [
        Declaration(agent_id="n1", delegate_to="n0"),
        Declaration(agent_id="n2", delegate_to="n1"),
        Declaration(agent_id="n3", delegate_to="n2"),
        Declaration(agent_id="n4", delegate_to="n3"),
    ]
    chain_reachable = depth_engine.resolve_reachable_tiers(chain_declarations)
    check(
        "②誘因構造層: max_chain_depthを超える連鎖(n0→…→n4のtier9)は到達可能集合に含まれない",
        chain_reachable["n0"] == 0,
    )

    # --- ⑤検証層: DisCoPyによる合成則チェック(共通実装) ------------------------------
    report = run_structural_verification(
        all_agent_ids=["admin", "deploy_svc", "ci_svc", "build_svc", "intern_svc"],
        write_own_domain_only=True,
    )
    check("⑤検証層: 構造検証(結合律・単位律・境界の型一致)がすべてPassする", report.all_passed)

    # --- 3シーン構成: 平常時→合成リスク注入→根本原因の特定(反実仮想) ------------------
    scene_env = EnvironmentClient(env_config)
    baseline_agents = [
        TrustDeclaringAgent("admin", None),
        TrustDeclaringAgent("deploy_svc", "ci_svc"),
        TrustDeclaringAgent("ci_svc", "build_svc"),
        TrustDeclaringAgent("build_svc", None),
        TrustDeclaringAgent("intern_svc", None),
    ]
    leak_agents = [LeakDetectingAgent(a, scene_env) for a in baseline_agents]

    scenes, esc_report = run_three_scene_demo(
        leak_agents,
        injected_agent_id="admin",
        injected_delegate_to="ci_svc",
        engine=engine,
        env=scene_env,
        scene1_rounds=3,
        scene2_rounds=3,
    )
    scene_names = [s.name for s in scenes]
    check(
        "3シーン構成: scene1(x3)→scene2(x3)の順に実行され、シーン3は計測レポートとして得られる",
        scene_names == ["scene1_baseline"] * 3 + ["scene2_trust_injected"] * 3,
    )
    check(
        "シーン1: 平常時は誰も権限昇格しない",
        all(s.outcome.result.allocated_agent_ids == [] for s in scenes if s.name == "scene1_baseline"),
    )
    check(
        "シーン2: adminの1件のtrust宣言追加(単独では局所的に正当)により、"
        "build_svc・ci_svcがadmin相当の権限に到達してしまう(誰も虚偽申告していない)",
        set(esc_report.scene2_escalated) == {"build_svc", "ci_svc"},
    )
    print(
        f"       (シーン2到達tier: {esc_report.scene2_reachable}、"
        f"昇格したエージェント: {esc_report.scene2_escalated})"
    )
    check(
        "シーン3(根本原因の特定、反実仮想): 注入した1件のtrust宣言(admin→ci_svc)"
        "だけを取り除くと、権限昇格経路は完全に消える",
        esc_report.root_cause_confirmed,
    )

    # --- chokepointランキング: どのtrust宣言を1件取り除けば最も効果的に解消できるか ---
    chokepoints = rank_chokepoint_edges(engine, scenes[-1].declarations)
    check(
        "chokepointランキング: 最も効果的なedge(注入されたadmin→ci_svc)が1位にランク"
        "され、build_svc・ci_svc両方の昇格を解消する",
        chokepoints[0].truster_agent_id == "admin"
        and chokepoints[0].trusted_agent_id == "ci_svc"
        and set(chokepoints[0].resolved_agent_ids) == {"build_svc", "ci_svc"},
    )
    check(
        "chokepointランキング: 昇格経路に無関係なedge(deploy_svc→ci_svc)を取り除いても"
        "昇格は一切解消しない(0件、優先度が正しく最下位になる)",
        any(
            c.truster_agent_id == "deploy_svc" and c.trusted_agent_id == "ci_svc" and c.escalations_resolved == 0
            for c in chokepoints
        ),
    )
    print(
        "       (chokepointランキング: "
        + ", ".join(
            f"{c.truster_agent_id}→{c.trusted_agent_id}(解消{c.escalations_resolved}件)" for c in chokepoints
        )
        + ")"
    )

    # --- 候補trust宣言の総当たりスキャン: まだ無い追加のうち何が危険かを事前に判定 -----
    candidates = scan_candidate_trust_grants(engine, scenes[0].declarations)
    check(
        "候補スキャン: 平常時の宣言に対し、trustをまだ与えていない3エージェント"
        "(admin/build_svc/intern_svc)×他4エージェント=12件の候補全てを評価する",
        len(candidates) == 12,
    )
    check(
        "候補スキャン: 実際に選んだシナリオ(admin→ci_svc)より危険な候補"
        "(admin→deploy_svc、admin→intern_svc)が存在し、1位にランクされる"
        "(手で選んだ1例が必ずしも最悪のケースとは限らない)",
        candidates[0].excess_introduced == 3
        and candidates[0].truster_agent_id == "admin"
        and candidates[0].trusted_agent_id in {"deploy_svc", "intern_svc"},
    )
    check(
        "候補スキャン: admin(最上位tier)が誰を信頼しても必ず危険(4件全てis_safe=False、"
        "最上位ロールがtrustを与える行為そのものが構造的にリスクを持つ)",
        all(c.is_safe is False for c in candidates if c.truster_agent_id == "admin"),
    )
    check(
        "候補スキャン: intern_svc(最下位tier)が誰を信頼しても安全(4件全てis_safe=True、"
        "最下位ロールが他者を信頼しても、他者の到達範囲は広がらない)",
        all(c.is_safe is True for c in candidates if c.truster_agent_id == "intern_svc"),
    )
    print(
        "       (危険な候補: "
        + ", ".join(
            f"{c.truster_agent_id}→{c.trusted_agent_id}(超過+{c.excess_introduced})"
            for c in candidates
            if not c.is_safe
        )
        + ")"
    )

    # --- 情報の非対称性の制御(#3、D-59の横展開) -------------------------------------
    check(
        f"3シーン構成(#3、情報の非対称性の制御): 全{total_checks(leak_agents)}回の"
        "意思決定タイミングで、同一ラウンド内の他者のtrust宣言が一度も見えていない",
        no_intra_round_leak(leak_agents),
    )

    print("すべての疎通確認に成功しました。")


if __name__ == "__main__":
    main()
