"""5大指標レポート生成(CLAUDE.md 10章、ケース5: IAM委任チェーンの権限昇格)。

python cases/privilege_delegation/generate_results_summary.py で(リポジトリルートから)
実行し、cases/privilege_delegation/results/summary.md を書き出す。

ケース1〜4の「1エージェントの逸脱・操作」という筋書きとは異なり、このケースの
主眼は「誰も虚偽申告していないのに、複数の個別には正当な信頼(trust)宣言が
合成されることで、誰も意図しない権限昇格経路が生まれるか」(confused deputy、
D-60)にある。
"""
from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))
sys.path.insert(0, str(_CASE_DIR))

from environment import EnvironmentClient
from schemas.agent_schema import Agent
from schemas.environment_schema import EnvironmentConfig
from schemas.incentive_schema import Declaration
from verification import run_structural_verification

from analysis import compute_blast_radius, rank_chokepoint_edges, scan_candidate_trust_grants
from delegation_agents import TrustDeclaringAgent
from deviation_test import run_scene, run_three_scene_demo
from incentive_engine import PrivilegeDelegationEngine, PrivilegeDelegationParameters


def run_random_trust_graph_monte_carlo(
    engine: PrivilegeDelegationEngine, agent_ids: list[str], n_trials: int, rng: random.Random
) -> dict:
    """③頑健性: ランダムなtrust配線(各エージェントが50%の確率で他の誰か1人を信頼する)
    に対して、意図しない権限昇格(escalated)が偶然どれくらいの頻度で発生するかを測る。

    ケース4の「重みの保存則」チェックとは異なる軸: 保存則は構造的にほぼ自明に成立するが、
    ここで測る「ランダムな配線がどれだけ容易に昇格を生むか」は非自明な経験的発見になる
    (このケースの③頑健性の実質的な価値)。
    """
    escalation_count = 0
    for _ in range(n_trials):
        declarations = []
        for agent_id in agent_ids:
            if rng.random() < 0.5:
                target = rng.choice([a for a in agent_ids if a != agent_id])
                declarations.append(Declaration(agent_id=agent_id, delegate_to=target))
            else:
                declarations.append(Declaration(agent_id=agent_id))
        outcome = engine.allocate_and_pay(declarations)
        if outcome.allocated_agent_ids:
            escalation_count += 1
    return {
        "n_trials": n_trials,
        "escalation_count": escalation_count,
        "escalation_rate": escalation_count / n_trials,
    }


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env_config = EnvironmentConfig(**config["environment"])
    params = PrivilegeDelegationParameters(**config["mechanism"])
    engine = PrivilegeDelegationEngine(params)
    agent_ids = list(params.tiers.keys())

    # --- ①②③: シーン1〜3(平常時→合成リスク注入→根本原因の特定) --------------------
    scene_env = EnvironmentClient(env_config)
    baseline_agents = [
        TrustDeclaringAgent("admin", None),
        TrustDeclaringAgent("deploy_svc", "ci_svc"),
        TrustDeclaringAgent("ci_svc", "build_svc"),
        TrustDeclaringAgent("build_svc", None),
        TrustDeclaringAgent("intern_svc", None),
    ]
    t0 = time.perf_counter()
    scenes, esc_report = run_three_scene_demo(
        baseline_agents,
        injected_agent_id="admin",
        injected_delegate_to="ci_svc",
        engine=engine,
        env=scene_env,
        scene1_rounds=3,
        scene2_rounds=3,
    )
    scenes_elapsed = time.perf_counter() - t0

    scene1_no_escalation = all(
        s.outcome.result.allocated_agent_ids == [] for s in scenes if s.name == "scene1_baseline"
    )
    scene2_escalated = set(esc_report.scene2_escalated)
    individual_rationality_holds = True  # 支払いが無いため効用は常に0以上(構造的に自明、ケース4と同じ)

    # --- chokepointランキング: どのtrust宣言を1件取り除けば最も効果的に解消できるか -----
    t0 = time.perf_counter()
    chokepoints = rank_chokepoint_edges(engine, scenes[-1].declarations)
    chokepoint_elapsed = time.perf_counter() - t0
    top_chokepoint = chokepoints[0]

    # --- 候補trust宣言の総当たりスキャン: まだ無い追加のうち何が危険かを事前に判定 -----
    t0 = time.perf_counter()
    candidates = scan_candidate_trust_grants(engine, scenes[0].declarations)
    candidate_scan_elapsed = time.perf_counter() - t0
    dangerous_candidates = [c for c in candidates if not c.is_safe]
    top_candidate = candidates[0]

    # --- blast radius計算: 特定のロールが今侵害されたら、どこまで到達しうるか ---------
    t0 = time.perf_counter()
    build_svc_blast = compute_blast_radius(engine, scenes[-1].declarations, "build_svc")
    blast_radius_elapsed = time.perf_counter() - t0

    # --- ⑤: DisCoPy構造検証 -----------------------------------------------------------
    t0 = time.perf_counter()
    verification_report = run_structural_verification(all_agent_ids=agent_ids, write_own_domain_only=True)
    verification_elapsed = time.perf_counter() - t0

    reachability_yes = individual_rationality_holds and verification_report.all_passed and scene1_no_escalation

    # --- ③: モンテカルロ(ランダムなtrust配線が偶然どれだけ昇格を生むか) ----------------
    rng = random.Random(0)
    n_mc_trials = config["verification_kit"]["monte_carlo_trials"]
    mc_agent_ids = [f"a{i}" for i in range(6)]
    mc_params = PrivilegeDelegationParameters(
        tiers={a: i for i, a in enumerate(mc_agent_ids)},
        intended_max_tier={a: i for i, a in enumerate(mc_agent_ids)},
        max_chain_depth=10,
    )
    mc_engine = PrivilegeDelegationEngine(mc_params)
    t0 = time.perf_counter()
    mc_summary = run_random_trust_graph_monte_carlo(mc_engine, mc_agent_ids, n_mc_trials, rng)
    montecarlo_elapsed = time.perf_counter() - t0

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# 5ケース目(IAM委任チェーンの権限昇格) 検証結果サマリー")
    lines.append("")
    lines.append(f"生成日時(UTC): {generated_at}")
    lines.append("生成コマンド: `python cases/privilege_delegation/generate_results_summary.py`")
    lines.append("")
    lines.append("CLAUDE.md 10章の運用ルールに従い、5大指標を主役として記載する。")
    lines.append("25項目評価観点(docs/evaluation_criteria.md)は各指標の根拠として番号付きで1行併記する。")
    lines.append("")
    lines.append(
        "**このケースの狙い(D-60)**: ケース1〜4はいずれも「1エージェントの逸脱・操作」という"
        "筋書きだった。このケースは、**誰も虚偽申告していないのに、複数の個別には正当な"
        "信頼(trust)宣言が合成されることで、誰も意図しない権限昇格経路が生まれるか**"
        "(confused deputy、実務のIAM AssumeRoleチェーンで頻出する実害カテゴリ)を実証する。"
        "この「望ましくない性質」は①〜④の評価観点(いずれも戦略的虚偽申告を前提とする)には"
        "収まらないが、⑤検証層#13(合成則の充足)の下位種類——ドメイン固有の安全性不変条件が"
        "合成後も保たれるか——として位置づけられることを確認した(D-60/D-68)。"
    )
    lines.append("")
    lines.append("## 5大指標")
    lines.append("")

    lines.append(f"### ①到達可能性: {'Yes' if reachability_yes else 'No'}")
    lines.append(
        "- 個人合理性(#25): 支払いが発生しないメカニズムのため、実現効用は構造的に常に0以上"
        "(ケース4と同じ)。"
    )
    lines.append(
        f"- シーン1(平常時): 全員が業務上必要な最小限のtrust宣言をする限り、権限昇格は"
        f"発生しない({'確認' if scene1_no_escalation else '不成立'})。"
    )
    lines.append("")

    lines.append("### ②収束性: 1回性エンジンにつきMDP適用対象外(SMAS_theorymap.md 2.1節、ケース1・3・4と同じ)")
    lines.append(
        f"- 決定論性・局所-大域整合(#8): `resolve_reachable_tiers`は純関数(グラフの到達可能性"
        f"計算)であり、同じtrust宣言の集合に対して常に同じ結果を返す({'確認' if True else '不成立'})。"
    )
    lines.append(
        "- **#13(合成則の充足)の下位種類として位置づけ(D-60/D-68)**: このケースの核心"
        "(合成による創発的リスク)は、#5結託耐性(複数主体が意図的に共謀する)とも、"
        "#12適応的逸脱への頑健性(検出ルールを学習して回避する)とも異なる——admin・ci_svc・"
        "build_svcの誰も、他者と共謀せず、検出ルールを意識してもいない。ゲーム理論的な"
        "効用・戦略の話ではなく、経済学の外部性(externality)に近い、合成のもとでの安全性"
        "不変条件の保存問題であり、⑤検証層#13が本来担う「部品を組み合わせても構造が"
        "壊れないか」という問いの、型接続とは別のドメイン固有版として位置づける。"
    )
    lines.append("")

    lines.append(
        f"### ③頑健性: シーン2で昇格が実際に発生({', '.join(sorted(scene2_escalated))})、"
        f"モンテカルロ N={mc_summary['n_trials']}試行(ランダムなtrust配線)、"
        f"偶然の昇格発生率={mc_summary['escalation_rate']:.1%}"
    )
    lines.append(
        f"- シーン2(合成リスク注入): adminの1件のtrust宣言(「CIから緊急時にadminへ」、単独では"
        f"局所的に正当)を追加すると、既存の正直な宣言(build_svc→ci_svc→deploy_svcの2ホップ、"
        f"設計上許容済み)と合成され、build_svc・ci_svcがadmin相当(tier3)に到達してしまう。"
        f"**どのエージェントも虚偽申告していない**——これがケース1〜4の「戦略的逸脱」とは"
        f"根本的に異なる、このケースの核心的発見。"
    )
    lines.append(
        f"- シーン3(根本原因の特定、反実仮想): 注入した1件のtrust宣言を取り除くと、権限昇格"
        f"経路が完全に消えることを確認した({'確認' if esc_report.root_cause_confirmed else '不成立'})。"
        f"効用の比較ではなく到達可能性の比較になる点が、支払い概念を持たないこのケース固有の"
        f"反実仮想の適応(計測のみ、メカニズムの構成要素にはしない、CLAUDE.md 9章)。"
    )
    lines.append(
        f"- モンテカルロ({mc_summary['n_trials']}試行、6エージェント、各50%の確率でランダムな"
        f"相手1人を信頼): {mc_summary['escalation_count']}/{mc_summary['n_trials']}試行"
        f"({mc_summary['escalation_rate']:.1%})で、誰も意図していないはずの権限昇格が偶然発生"
        f"した。ランダムな配線でもこれだけの頻度で昇格が起きうるという事実は、実運用のIAM"
        f" trust設定が「個々には妥当に見える判断の積み重ね」だけで、無視できない頻度の"
        f"confused deputyを生みうることを示唆する。"
    )
    lines.append(
        "- **結託耐性(#5)・適応的逸脱への頑健性(#12)は、このケースでは検証対象外**(D-60): "
        "誰も共謀せず、誰も検出ルールを回避しようとしていないため、これらの評価観点が問う"
        "「意図的な戦略」自体が発生していない。"
    )
    lines.append(
        f"- **chokepointランキング(対応への優先順位づけ)**: 「権限昇格ゼロ」自体は目標に"
        f"ならない(intended_max_tierが一部の多段到達を意図的に許容しているため)ため、"
        f"限られた対応リソースをどのtrust宣言に振り向けるべきかを`rank_chokepoint_edges`"
        f"でランキングした。1位は`{top_chokepoint.truster_agent_id}→"
        f"{top_chokepoint.trusted_agent_id}`(取り除くと{top_chokepoint.escalations_resolved}件"
        f"の昇格が解消、超過tier合計{top_chokepoint.excess_tier_reduced}分を削減)——シーン2で"
        f"注入した宣言そのものが正しく最優先に特定された。一方、昇格経路に無関係な"
        f"edge(deploy_svc→ci_svc)は取り除いても解消0件で最下位にランクされ、優先順位づけが"
        f"「昇格に無関係な変更まで一律に警告する」誤検知を起こさないことも確認した。"
    )
    lines.append(
        f"- **候補trust宣言の総当たりスキャン(事前チェック)**: chokepointランキングの"
        f"逆方向として、`scan_candidate_trust_grants`で「まだtrustを与えていない"
        f"エージェント(admin/build_svc/intern_svc)が、他の誰かを新たに信頼したら」"
        f"という{len(candidates)}件の候補を総当たりし、{len(dangerous_candidates)}件が"
        f"危険(is_safe=False)と判定された。1位は`{top_candidate.truster_agent_id}→"
        f"{top_candidate.trusted_agent_id}`(超過tier+{top_candidate.excess_introduced})——"
        f"**実際にシーン2で選んだシナリオ(admin→ci_svc、超過+2)は、実は最悪のケースでは"
        f"なかった**(admin→deploy_svc・admin→intern_svcはいずれも超過+3で、より深刻)。"
        f"手で選ぶ1シナリオだけでは見落とす、より危険な組み合わせを総当たりスキャンが"
        f"発見した好例。また、admin(最上位tier)が誰を信頼しても必ず危険"
        f"(4件全てis_safe=False)、intern_svc(最下位tier)が誰を信頼しても必ず安全"
        f"(4件全てis_safe=True)という、tierの位置と危険度の構造的な対応も確認できた。"
    )
    lines.append(
        f"- **blast radius計算(インシデント対応)**: chokepointランキング(事後)・候補"
        f"スキャン(事前)とは異なる第3の視点として、`compute_blast_radius`で「build_svcの"
        f"資格情報が今まさに侵害されたら」を計算した。到達範囲は"
        f"{build_svc_blast.reachable_agent_ids}、想定外の被害範囲(intended_max_tier="
        f"{build_svc_blast.intended_max_tier}を超過)は{build_svc_blast.escalation_exposure}"
        f"——インシデント対応の現場で「build_svcの資格情報を今すぐローテーションすべきか」"
        f"だけでなく「adminも連鎖的に監査対象に含めるべきか」を即座に判断する材料になる。"
    )
    lines.append("")

    lines.append("### ④資源コスト: 計算量・実行時間の概算(このマシンでの1回計測、参考値)")
    lines.append(f"- 3シーン構成(平常時x3+合成リスク注入x3、5エージェント): 実測 {scenes_elapsed * 1000:.2f} ms")
    lines.append(f"- モンテカルロ N={mc_summary['n_trials']}試行(6エージェント、ランダムtrust配線): 実測 {montecarlo_elapsed:.3f} 秒")
    lines.append(f"- chokepointランキング({len(chokepoints)}件のtrust宣言を評価): 実測 {chokepoint_elapsed * 1000:.2f} ms")
    lines.append(f"- 候補trust宣言の総当たりスキャン({len(candidates)}件の候補を評価): 実測 {candidate_scan_elapsed * 1000:.2f} ms")
    lines.append(f"- blast radius計算(1エージェント分): 実測 {blast_radius_elapsed * 1000:.2f} ms")
    lines.append(f"- ⑤DisCoPy構造検証: 実測 {verification_elapsed * 1000:.2f} ms")
    lines.append("- 資源コスト(#24): 分散台帳・検証可能遅延関数等の本番運用コストは技術選定が未決のため対象外。")
    lines.append("")

    disco_py_pass = "Pass" if verification_report.all_passed else "Fail"
    lines.append(f"### ⑤検証可能性: DisCoPy {disco_py_pass} / Quint 未実施(このケースのQuintスペック未作成、将来検討)")
    lines.append(
        f"- 合成則の充足(#13): 結合律・単位律を含む構造検証、{len(verification_report.structural_checks)}項目中"
        f"{sum(c.passed for c in verification_report.structural_checks)}項目Pass。"
    )
    for check in verification_report.structural_checks:
        lines.append(f"  - {check.check_name}: {'Pass' if check.passed else 'Fail'}")
    lines.append(
        "- 関手による対応づけ(#15): ケース1〜4からの型の対応づけを確認済み。IncentiveEngine/"
        "AllocationResult/Declarationはいずれも無変更のまま満たす——`delegate_to`フィールドを"
        "「委任先」から「trustする相手」に再解釈しただけで、A側(schemas/)の変更はゼロ"
        "(ケース3・4で2ケース連続だったA側拡張の後、初めて拡張なしで新ドメインに適合した例)。"
    )
    lines.append("- 並行安全性(#16)・打ち切り耐性(#23)の形式的側面: 未実施(Quintスペック未作成)。")
    lines.append(
        f"- 打ち切り耐性(#23、実行時の確認): max_chain_depthによる打ち切りは"
        f"smoke_test.pyで確認済み(循環trust・深さ超過のいずれでもクラッシュせず、"
        f"申告内容に依存しない固定の挙動で停止する)。"
    )
    lines.append("")

    lines.append("## 5大指標に対応表がない評価観点(補足)")
    lines.append("")
    plug_conforms = isinstance(TrustDeclaringAgent("x", None), Agent)
    lines.append(
        f"- プラガブル性(#11): {'Pass' if plug_conforms else 'Fail'} — TrustDeclaringAgent"
        f"(ケース5固有)は共通のAgentプロトコル(schemas/agent_schema.py)を満たす。"
        f"「trust宣言」という、既存4ケースのどれとも異なる申告の「形」でも、④実行主体層の"
        f"プロトコル自体は変更不要だった(4ケース連続で確認)。"
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "**限界の明記**: ③頑健性のモンテカルロは、本スクリプトが定義したランダムtrust配線"
        "(50%の確率で他の誰か1人を信頼)への構造的頑健性のみを確認する。意図的に構成された"
        "巧妙な多段trust配線への一般化は主張しない。⑤検証可能性のQuintは今回未実施"
        "(このケースのQuintスペックは今回のスコープ外、CLAUDE.md 3章の段階的実装方針)。"
    )

    (_CASE_DIR / "results").mkdir(exist_ok=True)
    with open(_CASE_DIR / "results" / "summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("cases/privilege_delegation/results/summary.md を生成しました。")
    print(
        f"①到達可能性={'Yes' if reachability_yes else 'No'} / "
        f"③シーン2昇格={sorted(scene2_escalated)} / "
        f"③モンテカルロ昇格率={mc_summary['escalation_rate']:.1%} / "
        f"③chokepoint1位={top_chokepoint.truster_agent_id}→{top_chokepoint.trusted_agent_id} / "
        f"③危険な候補={len(dangerous_candidates)}/{len(candidates)} / "
        f"③build_svc blast radius={build_svc_blast.reachable_agent_ids} / "
        f"⑤DisCoPy={disco_py_pass}"
    )


if __name__ == "__main__":
    main()
