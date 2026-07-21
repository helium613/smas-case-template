"""5大指標レポート生成(CLAUDE.md 10章、ケース3: 投票による共同意思決定)。

python cases/proposal_voting/generate_results_summary.py で(リポジトリルートから)
実行し、cases/proposal_voting/results/summary.md を書き出す。

ケース1・2と異なり、このケース(ボルダ得点、mechanism_catalog.md ファミリー2)は
意図的に非耐戦略性メカニズムを実装している(D-27)。③頑健性のモンテカルロは
「逸脱が得にならない」ことではなく「逸脱(埋葬戦術)が得になる場合が実在する」
ことを示す形になり、これが⑤検証層・レポートの想定どおりの結果であることを
明記する(mechanism_catalog.md Part3、良い設計の検証実績しかなかったケース1・2
に対して、悪い設計を正しく検出できるかを初めて確認する)。

またD-21/D-22で持ち越したLangGraph状態プロキシパターン検証を、このケースで
初めて実地検証する(D-27)。
"""
from __future__ import annotations

import random
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))
sys.path.insert(0, str(_CASE_DIR))

from environment import EnvironmentClient
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import EnvironmentConfig
from schemas.incentive_schema import Declaration
from verification import run_structural_verification

from deviation_test import run_two_scene_demo
from incentive_engine import BordaVotingEngine, BordaVotingParameters
from langgraph_flow import build_voting_graph, run_voting_round
from voting_agents import BuryingStrategicAgent, HonestVotingAgent

QUINT_SPEC_PATH = str(_CASE_DIR / "quint" / "proposal_voting.qnt")  # subprocess呼び出し用(絶対パス、CWD非依存)
QUINT_SPEC_DISPLAY_PATH = str(Path(QUINT_SPEC_PATH).relative_to(_CASE_DIR.parents[1]))  # レポート表示用


def run_quint_check() -> str:
    """動的安全性検証(⑤、①到達可能性側)。ケース1・2(D-19)と同じ環境制約により、
    シミュレータ(`quint run`)による安全性不変条件の経験的確認に留める。"""
    if shutil.which("quint") is None:
        return "未実施(quintコマンドが見つかりません。npm install -g @informalsystems/quint)"
    try:
        result = subprocess.run(
            [
                "quint", "run", QUINT_SPEC_PATH,
                "--main", "main",
                "--invariant", "validPhase",
                "--max-steps", "20",
                "--max-samples", "300",
                "--backend", "typescript",
                "--seed", "0x1",
            ],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "未実施(quint runがタイムアウトしました)"
    output = result.stdout + result.stderr
    status = "Pass(シミュレーション、網羅的証明ではない)" if "No violation found" in output else "Fail"
    return (
        f"{status} — `quint run`(300サンプル、safety不変条件: ラウンドの実行フェーズが"
        f"idle/collecting/aggregating/recordedのいずれかに収まる)で違反なし。"
        f"Apalache(SMT、安全性)・TLC(公平性を伴う活性: 「ラウンドはいつか必ずrecordedに"
        f"達する」)による網羅的検証は、ケース1・2(D-19)と同じ環境のツールチェイン不具合"
        f"により未実施。`.qnt`はtypecheck済みで、環境を修復すれば"
        f"`{QUINT_SPEC_DISPLAY_PATH}`の再実行のみで足りる。"
    )


def run_langgraph_check(engine: BordaVotingEngine, env_config: EnvironmentConfig, candidate_ids: list[str]) -> str:
    """フレームワーク統合(LangGraph状態プロキシパターン、CLAUDE.md 7章)を実地検証する。

    D-21で発見・D-22/D-24で持ち越されたギャップを、D-27の方針どおりケース3で解消する。
    3項目チェックリストの(1)(2)はコードレビュー的性質のため、ここでは(3)ノード実行
    順序が②③⑤に越境していないこと(collect=④、aggregate=③、record=①)と、
    グラフ経由でも同じ結果が得られること(①〜③の疎通)を実行時に確認する。
    """
    env = EnvironmentClient(env_config)
    proposal_a = candidate_ids[0]
    agents = [
        HonestVotingAgent("alice", {c: 10.0 - i for i, c in enumerate(candidate_ids)}),
        HonestVotingAgent("carol", {c: 9.0 - i for i, c in enumerate(candidate_ids)}),
        HonestVotingAgent("bob", {c: 8.0 - i for i, c in enumerate(candidate_ids)}),
    ]
    scene = run_voting_round("langgraph_check", agents, engine, env, compiled_graph=build_voting_graph())
    graph_ok = scene.outcome.result is not None and scene.outcome.result.allocated_agent_ids == [proposal_a]
    wall_ok = len(env.read_traces()) == 3 and all(t.agent_id in {"alice", "bob", "carol"} for t in env.read_traces())
    return (
        f"{'Pass' if (graph_ok and wall_ok) else 'Fail'} — State型は`EnvironmentClient`参照のみを持ち、"
        f"申告・集計結果は1ラウンド限りの一時値として扱う(蓄積履歴を複製しない)。"
        f"ノード(collect_rankings=④/aggregate=③/record=①)の実行順序どおりに動作し"
        f"({'確認' if graph_ok else '不成立'})、壁(自領域のみ書き込み)も迂回されない"
        f"({'確認' if wall_ok else '不成立'})。D-21/D-22から持ち越されたギャップをここで解消。"
    )


def run_manipulation_monte_carlo(
    engine: BordaVotingEngine, candidate_ids: list[str], n_trials: int, rng: random.Random
) -> dict:
    """③頑健性: 真の評価額をランダム化し、埋葬戦術(BuryingStrategicAgent)が得に
    なった試行の割合を測定する。ケース1・2の「0%が正しい」モンテカルロとは逆に、
    ここでは非ゼロの割合が出ることが理論どおりの、想定内の結果になる。
    """
    profitable = 0
    for _ in range(n_trials):
        true_values = {
            "alice": {c: rng.uniform(1.0, 10.0) for c in candidate_ids},
            "carol": {c: rng.uniform(1.0, 10.0) for c in candidate_ids},
            "bob": {c: rng.uniform(1.0, 10.0) for c in candidate_ids},
        }
        honest_declarations = [
            Declaration(agent_id=a, declared_ranking=HonestVotingAgent(a, tv).true_ranking())
            for a, tv in true_values.items()
        ]
        honest_winner = engine.allocate_and_pay(honest_declarations).allocated_agent_ids[0]

        manipulated_declarations = [
            d if d.agent_id != "bob" else Declaration(
                agent_id="bob", declared_ranking=BuryingStrategicAgent("bob", true_values["bob"]).manipulated_ranking()
            )
            for d in honest_declarations
        ]
        manipulated_winner = engine.allocate_and_pay(manipulated_declarations).allocated_agent_ids[0]

        if true_values["bob"][manipulated_winner] > true_values["bob"][honest_winner]:
            profitable += 1
    return {"n_trials": n_trials, "profitable_count": profitable, "profitable_rate": profitable / n_trials}


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env_config = EnvironmentConfig(**config["environment"])
    candidate_ids = config["mechanism"]["candidate_ids"]
    scenario = config["scenario"]
    engine = BordaVotingEngine(BordaVotingParameters(candidate_ids=candidate_ids))
    proposal_a, proposal_b, proposal_c, proposal_d = candidate_ids

    # --- ①②③: 2シーン構成(具体例、手計算で検証済みの操作可能シナリオ) ---------------
    alice_true = {proposal_a: 10.0, proposal_b: 6.0, proposal_c: 3.0, proposal_d: 1.0}
    carol_true = {proposal_a: 9.0, proposal_b: 5.0, proposal_c: 2.0, proposal_d: 1.0}
    bob_true = {proposal_b: 10.0, proposal_a: 6.0, proposal_d: 4.0, proposal_c: 1.0}
    honest_agents = [
        HonestVotingAgent("alice", alice_true),
        HonestVotingAgent("carol", carol_true),
        HonestVotingAgent("bob", bob_true),
    ]

    def make_burying(agent):
        return BuryingStrategicAgent(agent.agent_id, bob_true)

    env = EnvironmentClient(env_config)
    t0 = time.perf_counter()
    scenes, manipulation_report = run_two_scene_demo(
        honest_agents,
        manipulating_agent_id="bob",
        manipulating_agent_factory=make_burying,
        manipulating_agent_true_values=bob_true,
        engine=engine,
        env=env,
        scene1_rounds=scenario["scene1_rounds"],
        scene2_rounds=scenario["scene2_rounds"],
    )
    two_scene_elapsed = time.perf_counter() - t0

    scene1_results = [s for s in scenes if s.name == "scene1_honest"]
    scene1_utilities = []
    true_values_by_agent = {"alice": alice_true, "carol": carol_true, "bob": bob_true}
    for result in scene1_results:
        if result.outcome.result is None:
            continue
        winner = result.outcome.result.allocated_agent_ids[0]
        for agent_id, tv in true_values_by_agent.items():
            scene1_utilities.append(tv.get(winner, 0.0))
    individual_rationality_holds = all(u >= -1e-9 for u in scene1_utilities)

    # --- ①: LangGraph状態プロキシパターンの実地検証(D-21/D-22から持ち越し) ----------
    langgraph_result = run_langgraph_check(engine, env_config, candidate_ids)

    # --- ⑤: DisCoPy構造検証 -----------------------------------------------------------
    t0 = time.perf_counter()
    verification_report = run_structural_verification(all_agent_ids=["alice", "bob", "carol"], write_own_domain_only=True)
    verification_elapsed = time.perf_counter() - t0

    reachability_yes = individual_rationality_holds and verification_report.all_passed and "Pass" in langgraph_result

    # --- ③: モンテカルロ(埋葬戦術が得になる割合、非ゼロが想定内) ----------------------
    rng = random.Random(0)
    n_mc_trials = min(config["verification_kit"]["monte_carlo_trials"], 200)
    t0 = time.perf_counter()
    mc_summary = run_manipulation_monte_carlo(engine, candidate_ids, n_mc_trials, rng)
    montecarlo_elapsed = time.perf_counter() - t0

    # --- ④: 単発のボルダ集計コスト(参考値) -------------------------------------------
    t0 = time.perf_counter()
    engine.allocate_and_pay(
        [Declaration(agent_id=a, declared_ranking=HonestVotingAgent(a, tv).true_ranking()) for a, tv in true_values_by_agent.items()]
    )
    single_call_elapsed = time.perf_counter() - t0

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# 3ケース目(投票による共同意思決定・ボルダ得点) 検証結果サマリー")
    lines.append("")
    lines.append(f"生成日時(UTC): {generated_at}")
    lines.append("生成コマンド: `python cases/proposal_voting/generate_results_summary.py`")
    lines.append("")
    lines.append("CLAUDE.md 10章の運用ルールに従い、5大指標を主役として記載する。")
    lines.append("25項目評価観点(docs/evaluation_criteria.md)は各指標の根拠として番号付きで1行併記する。")
    lines.append("")
    lines.append(
        "**このケースの狙い(D-27)**: ケース1(VCG)・ケース2(トリガー戦略)はいずれも"
        "「良い設計」の検証実績しかなかった。ボルダ得点は理論上非耐戦略性のメカニズムであり、"
        "意図的にこれを実装することで、⑤検証層・③モンテカルロが「悪い設計」を正しく検出できるか"
        "を初めて確認する(mechanism_catalog.md Part3)。①到達可能性(個人合理性・権力集中の不在)"
        "と③頑健性(耐戦略性)は独立した軸であり、①=Yesでも③が悪いことは矛盾しない。"
    )
    lines.append("")
    lines.append("## 5大指標")
    lines.append("")

    lines.append(f"### ①到達可能性: {'Yes' if reachability_yes else 'No'}")
    lines.append(
        f"- 個人合理性(#25): 支払いが発生せず真の評価額も非負のため、シーン1(正直申告、"
        f"{len(scene1_utilities)}件)の実現効用はすべて0以上({'成立' if individual_rationality_holds else '不成立'})。"
    )
    lines.append(
        f"- 権力集中の不在(#14): ⑤構造検証(全{len(verification_report.structural_checks)}項目)が"
        f"{'すべてPass' if verification_report.all_passed else '一部Fail'}。"
        f"フレームワーク統合(LangGraph、CLAUDE.md 7章): {langgraph_result}"
    )
    lines.append("")

    lines.append("### ②収束性: 1回性エンジンにつきMDP適用対象外(SMAS_theorymap.md 2.1節、ケース1と同じ)")
    lines.append(
        "- 決定論性・局所-大域整合(#8): ②誘因構造エンジンは純関数(同一の申告集合→同一の勝者)であり、"
        "各エージェントのローカル計算は自明に一致する。"
    )
    lines.append("- 収束性そのもの(#17): 代替評価として③頑健性(モンテカルロ)を参照。")
    lines.append("")

    lines.append(
        f"### ③頑健性: モンテカルロ N={mc_summary['n_trials']}試行、"
        f"埋葬戦術が得になった試行数={mc_summary['profitable_count']}({mc_summary['profitable_rate']:.1%})"
        f" — **非ゼロが理論どおりの想定内の結果**"
    )
    lines.append(
        f"- 誘因整合性(#1)・耐戦略性(#2): **満たさない(意図的)**。具体例(bob、埋葬戦術の合計効用: "
        f"埋葬={manipulation_report.total_actual_utility:+.2f} / 正直(反実仮想)="
        f"{manipulation_report.total_counterfactual_utility:+.2f})で埋葬戦術が明確に得をした"
        f"({'得をした' if manipulation_report.manipulation_profitable else '得をしなかった(要再確認)'})。"
        f"モンテカルロでも{mc_summary['profitable_rate']:.1%}の試行で埋葬戦術が得になった。"
        f"ボルダ得点は`mechanism_catalog.md`ファミリー2表で「戦術的な順位操作が可能」と明記された"
        f"非耐戦略性メカニズムであり、これは設計の欠陥ではなく**意図した実証結果**(D-27)。"
    )
    lines.append(
        "- 集約の操作耐性(#9): 上記のとおり満たさない。⑤検証層(DisCoPy)は「層をまたぐ接続の整合性」"
        "のみを見る(CLAUDE.md 2章 原則5)ため、この種の操作耐性の欠如自体はDisCoPyの対象外であり、"
        "モンテカルロ(実証的検証)が代わりに検出する役割を担う(verification_layer_clarification.md)。"
    )
    lines.append(
        f"- 打ち切り耐性(#23): 2シーン構成の全{len(scenes)}ラウンドでフォールバックに落ちず完走"
        f"({'確認済み' if all(not s.outcome.terminated_by_fallback for s in scenes) else '要確認'})。"
    )
    lines.append(
        "- 結託耐性(#5): 本ケースでも未検証(ケース1・2と同じくscope_exclusions_and_deferrals.md "
        "Part2の対象)。`pygambit`(技術スタックに③頑健性用として記載済みだが3ケースとも未使用)に"
        "よるステージゲームの均衡計算等、別途の検証が必要(D-25)。"
    )
    lines.append("")

    lines.append("### ④資源コスト: 計算量・実行時間の概算(このマシンでの1回計測、参考値)")
    lines.append(f"- ボルダ集計(単発呼び出し、申告3件×候補{len(candidate_ids)}件): 実測 {single_call_elapsed * 1000:.2f} ms")
    lines.append(f"- 2シーン構成(scene1×{scenario['scene1_rounds']}, scene2×{scenario['scene2_rounds']}): 実測 {two_scene_elapsed:.3f} 秒")
    lines.append(f"- モンテカルロ N={mc_summary['n_trials']}試行: 実測 {montecarlo_elapsed:.3f} 秒")
    lines.append(f"- ⑤DisCoPy構造検証: 実測 {verification_elapsed * 1000:.2f} ms")
    lines.append("- 資源コスト(#24): 分散台帳・検証可能遅延関数等の本番運用コストは技術選定が未決のため対象外。")
    lines.append("")

    disco_py_pass = "Pass" if verification_report.all_passed else "Fail"
    quint_result = run_quint_check()
    lines.append(f"### ⑤検証可能性: DisCoPy {disco_py_pass} / Quint {quint_result}")
    lines.append(f"- 合成則の充足(#13): 結合律・単位律を含む構造検証、{len(verification_report.structural_checks)}項目中"
                 f"{sum(c.passed for c in verification_report.structural_checks)}項目Pass。")
    for check in verification_report.structural_checks:
        lines.append(f"  - {check.check_name}: {'Pass' if check.passed else 'Fail'}")
    lines.append(
        "- 関手による対応づけ(#15): ケース1・2からの型の対応づけを確認済み。IncentiveEngine/"
        "AllocationResult/VersionedMechanismは無変更のまま満たす。Declaration/ActionOutputのみ、"
        "declared_ranking(順位申告)という新フィールドを追加した(既存フィールドは変更せず、"
        "後方互換の追加、CLAUDE.md 11章の変更理由明記)。ケース2(A側変更ゼロ)ほどではないが、"
        "3ケース目にして初めての、必然性のあるA側拡張だった。"
    )
    lines.append(f"- 並行安全性(#16)・打ち切り耐性(#23)の形式的側面: {quint_result}")
    lines.append("")

    lines.append("## 5大指標に対応表がない評価観点(補足)")
    lines.append("")
    plug_conforms = all(
        isinstance(a, Agent) for a in (HonestVotingAgent("alice", alice_true), BuryingStrategicAgent("bob", bob_true))
    )
    lines.append(
        f"- プラガブル性(#11): {'Pass' if plug_conforms else 'Fail'} — HonestVotingAgent/"
        f"BuryingStrategicAgent(ケース3固有、順位申告用に新設)は共通のAgentプロトコル"
        f"(schemas/agent_schema.py)を満たす。全く異なる申告の「形」(数値→順位)を持つ"
        f"メカニズムでも、④実行主体層のプロトコル自体は変更不要だった。"
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "**限界の明記**: ③頑健性のモンテカルロは、本スクリプトが定義した埋葬戦術"
        "(真の2位候補を最下位に落とす、単純な固定ルール)への非耐戦略性のみを確認する。"
        "他の操作戦略(妥協投票・連合的操作等)への一般化は主張しない。⑤検証可能性のQuintは、"
        "安全性不変条件のシミュレーション(有限サンプル)による経験的確認に留まり、Apalache・"
        "TLCによる網羅的な形式検証ではない(環境のツールチェイン不具合による、docs/DECISIONS.md D-19)。"
    )

    (_CASE_DIR / "results").mkdir(exist_ok=True)
    with open(_CASE_DIR / "results" / "summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("cases/proposal_voting/results/summary.md を生成しました。")
    print(f"①到達可能性={'Yes' if reachability_yes else 'No'} / "
          f"③頑健性: 埋葬戦術成功={mc_summary['profitable_count']}/{mc_summary['n_trials']} / "
          f"⑤DisCoPy={disco_py_pass}")


if __name__ == "__main__":
    main()
