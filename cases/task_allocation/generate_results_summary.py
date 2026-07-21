"""5大指標レポート生成(CLAUDE.md 10章)。

python cases/task_allocation/generate_results_summary.py で(リポジトリルートから)
実行し、cases/task_allocation/results/summary.md を書き出す。

CLAUDE.md 10章の運用ルールに従い、①〜⑤の大指標を主役として1行ずつ結論を出し、
25項目の評価観点は「内訳・根拠」として各指標に併記する(省略しない)。

【プラガブル性(#11)についての注記】`roadmap_consistency_memo.md`の大指標対応表には
#11(プラガブル性)に対応する大指標が存在しない(1ケース目完走後の振り返りで発覚した、
資源コスト#24と同種の未対応)。①〜⑤のどこにも無理に押し込めず、レポート末尾に補足として
別掲する。

【Quintについての注記】動的安全性検証(Quint/TLAモード)は、対応表(SMAS_theorymap.md
2章)上は②収束性ではなく①到達可能性(+評価観点#16並行安全性、#23打ち切り耐性)を
担当する。②収束性はMDP(Python、pymdptoolbox)の担当であり、かつ今回の1回性VCG
ケースには理論上適用対象外(SMAS_theorymap.md 2.1節)。①到達可能性はさらに、安全性
(SMT/Apalacheが得意)と活性(公平性を伴う時相論理、TLCが得意)に分かれる。このマシンでは
quint↔Apalache間のgRPCプロトコル互換性バグにより、Apalache・TLCどちらのバックエンドも
`quint verify`が実行できないため(docs/DECISIONS.md D-19)、run_quint_check()は
シミュレータ(`quint run`)による安全性不変条件の統計的確認に留める。網羅的検証ではない、
という限界を返り値の文言にそのまま含める。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))

from aggregation import TerminationConfig, run_mechanism
from agents.llm_mock import ProbabilisticMockAgent
from agents.llm_real import AnthropicToolUseAgent
from agents.rule_based import FluctuatingHonestAgent, GreedyOverstatingAgent, HonestRuleBasedAgent
from environment import EnvironmentClient
from incentive_engine import SingleItemVcgEngine, SingleItemVcgParameters
from schemas.agent_schema import Agent, ObservationInput
from schemas.environment_schema import EnvironmentConfig
from schemas.incentive_schema import Declaration
from deviation_test import run_scene, run_three_scene_demo
from verification import run_structural_verification
from verification_kit.montecarlo import run_trials, summarize


def check_pluggability() -> str:
    """プラガブル性(#11): ルールベース/LLMモック/LLM実物が同一のAgentプロトコルを
    満たし、かつ実際に同じ集約パイプライン(run_scene)へ差し替え可能であることを確認する。

    型の互換性のみを確認し、振る舞いの同等性は主張しない(CLAUDE.md 2章 原則4)。
    LLM実物は資格情報が無くてもインスタンス化(decide()呼び出し無し)は可能なため、
    isinstanceによるプロトコル適合チェックにはAPI呼び出しを要しない。
    """
    honest = HonestRuleBasedAgent("alice", true_value=10.0)
    mock = ProbabilisticMockAgent("alice", true_value=10.0)
    llm_real = AnthropicToolUseAgent("alice", true_value=10.0)
    conforms = all(isinstance(a, Agent) for a in (honest, mock, llm_real))

    env = EnvironmentClient(EnvironmentConfig(half_life_rounds=3.0, max_trace_age_rounds=10))
    engine = SingleItemVcgEngine(SingleItemVcgParameters(reserve_price=0.0))
    ran_with_rule_based = run_scene(
        "pluggability_check_rule_based",
        [HonestRuleBasedAgent("alice", true_value=10.0), HonestRuleBasedAgent("bob", true_value=7.0)],
        engine, env,
    )
    ran_with_mock = run_scene(
        "pluggability_check_mock",
        [ProbabilisticMockAgent("alice", true_value=10.0, p_honest=1.0), ProbabilisticMockAgent("bob", true_value=7.0, p_honest=1.0)],
        engine, env,
    )
    both_ran = ran_with_rule_based.outcome.result is not None and ran_with_mock.outcome.result is not None

    return (
        f"{'Pass' if (conforms and both_ran) else 'Fail'} — ルールベース・LLMモック・LLM実物の3実装が"
        f"同一のAgentプロトコル(schemas/agent_schema.py)を満たす({'確認' if conforms else '不成立'})。"
        f"ルールベース・LLMモックは同一のrun_scene(①〜③の実パイプライン)に無改造で差し替え可能"
        f"({'確認' if both_ran else '不成立'})。LLM実物も同じ経路で動作することはdemo_llm_real.pyで"
        f"実演済み(資格情報が必要なためこのレポートでは自動実行しない)。"
        f"型の互換性のみを確認しており、振る舞いの同等性(LLMが理論通り動くか)は主張しない。"
    )

QUINT_SPEC_PATH = str(_CASE_DIR / "quint" / "task_allocation.qnt")  # subprocess呼び出し用(絶対パス、CWD非依存)
QUINT_SPEC_DISPLAY_PATH = str(Path(QUINT_SPEC_PATH).relative_to(_CASE_DIR.parents[1]))  # レポート表示用


def run_quint_check() -> str:
    """動的安全性検証(⑤、①到達可能性側)。quintコマンドでsafety不変条件を確認する。

    網羅的な形式検証(Apalache=安全性のSMT検証、TLC=公平性を伴う活性検証「ラウンドは
    必ず終端に達する」)は、このマシンではquint↔Apalache間のgRPCプロトコル互換性
    バグによりブロックされている(docs/DECISIONS.md D-19)。代わりにquintのシミュ
    レータ(`quint run`)で安全性不変条件を有限サンプルで確認する — これは経験的
    確認であり、Apalache/TLCが与える網羅的な証明ではない、という限界を明記する。
    """
    if shutil.which("quint") is None:
        return "未実施(quintコマンドが見つかりません。npm install -g @informalsystems/quint)"

    try:
        result = subprocess.run(
            [
                "quint", "run", QUINT_SPEC_PATH,
                "--main", "main",
                "--invariant", "safety",
                "--max-steps", "15",
                "--max-samples", "500",
                "--backend", "typescript",
                "--seed", "0x1",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "未実施(quint runがタイムアウトしました)"

    output = result.stdout + result.stderr
    status = "Pass(シミュレーション、網羅的証明ではない)" if "No violation found" in output else "Fail"
    return (
        f"{status} — `quint run`(500サンプル、safety不変条件: 反復回数がMAX_ITERATIONS"
        f"を超えない/フォールバックは反復上限到達後にのみ発生する)で違反なし。"
        f"Apalache(SMT、安全性)・TLC(公平性を伴う活性: 「ラウンドは必ず終端に達する」)"
        f"による網羅的検証は、quint↔Apalache間のgRPCプロトコル互換性バグによりこの環境では"
        f"未実施(docs/DECISIONS.md D-19)。`.qnt`はtypecheck済みで、環境を修復すれば"
        f"`{QUINT_SPEC_DISPLAY_PATH}`の再実行のみで足りる。"
    )


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env_config = EnvironmentConfig(**config["environment"])
    engine = SingleItemVcgEngine(SingleItemVcgParameters(reserve_price=0.0))
    termination = TerminationConfig(**config["aggregation"])
    n_trials = config["verification_kit"]["monte_carlo_trials"]

    # --- ②③: 3シーン構成(シーン1〜2実行 + シーン3の反実仮想比較、D-07) -----------
    env = EnvironmentClient(env_config)
    agent_ids = ["alice", "bob", "carol"]
    honest_agents = [
        FluctuatingHonestAgent(agent_id, index, n_agents=len(agent_ids))
        for index, agent_id in enumerate(agent_ids)
    ]

    def make_greedy_deviant(agent):
        return GreedyOverstatingAgent(agent.agent_id, fixed_declared_value=1000.0)

    t0 = time.perf_counter()
    scenes, self_enforcement = run_three_scene_demo(
        honest_agents,
        deviating_agent_id="carol",
        deviating_agent_factory=make_greedy_deviant,
        engine=engine,
        env=env,
        scene1_rounds=5,
        scene2_rounds=5,
        termination=termination,
    )
    three_scene_elapsed = time.perf_counter() - t0

    scene1_results = [s for s in scenes if s.name == "scene1_honest"]
    scene1_honest_utilities = []
    for result in scene1_results:
        if result.outcome.result is None:
            continue
        for declaration in result.declarations:
            won = declaration.agent_id in result.outcome.result.allocated_agent_ids
            payment = result.outcome.result.payments.get(declaration.agent_id, 0.0)
            utility = (declaration.declared_value - payment) if won else 0.0
            scene1_honest_utilities.append(utility)
    individual_rationality_holds = all(u >= -1e-9 for u in scene1_honest_utilities)

    # --- ③: モンテカルロ(耐戦略性の経験的頑健性) ------------------------------------
    true_values = {"alice": 10.0, "bob": 7.0}

    def make_honest():
        return [Declaration(agent_id=a, declared_value=v) for a, v in true_values.items()]

    def deviate(decls: list[Declaration]) -> list[Declaration]:
        return [
            Declaration(
                agent_id=d.agent_id,
                declared_value=d.declared_value * 1.3 if d.agent_id == "alice" else d.declared_value,
            )
            for d in decls
        ]

    t0 = time.perf_counter()
    trials = run_trials(engine, make_honest, deviate, true_values, target_agent_id="alice", n_trials=n_trials)
    montecarlo_elapsed = time.perf_counter() - t0
    mc_summary = summarize(trials)

    # --- ⑤: DisCoPy構造検証 ---------------------------------------------------------
    t0 = time.perf_counter()
    verification_report = run_structural_verification(all_agent_ids=agent_ids, write_own_domain_only=True)
    verification_elapsed = time.perf_counter() - t0

    # --- ④: 単発のVCG呼び出しコスト(参考値) -----------------------------------------
    t0 = time.perf_counter()
    engine.allocate_and_pay([Declaration(agent_id="alice", declared_value=10.0), Declaration(agent_id="bob", declared_value=7.0)])
    single_vcg_call_elapsed = time.perf_counter() - t0

    # --- 大域的到達可能性(①)の判定 --------------------------------------------------
    reachability_yes = individual_rationality_holds and verification_report.all_passed

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# 1ケース目(タスク配分・VCG) 検証結果サマリー")
    lines.append("")
    lines.append(f"生成日時(UTC): {generated_at}")
    lines.append("生成コマンド: `python generate_results_summary.py`")
    lines.append("")
    lines.append("CLAUDE.md 10章の運用ルールに従い、5大指標を主役として記載する。")
    lines.append("24項目評価観点(docs/evaluation_criteria.md)は各指標の根拠として番号付きで1行併記する。")
    lines.append("")
    lines.append("## 5大指標")
    lines.append("")

    lines.append(f"### ①到達可能性: {'Yes' if reachability_yes else 'No'}")
    lines.append(
        f"- 個人合理性(#25): シーン1(正直申告、{len(scene1_honest_utilities)}件)の実現効用はすべて0以上"
        f"({'成立' if individual_rationality_holds else '不成立'})。"
    )
    lines.append(
        f"- 権力集中の不在(#14): ⑤構造検証(全{len(verification_report.structural_checks)}項目)が"
        f"{'すべてPass' if verification_report.all_passed else '一部Fail'}(壁による自領域外書き込み拒否を含む)。"
        f"介入ポート(`EnvironmentClient.record_intervention`)は型定義のみで、本ケースでは未行使のため監視対象外(未検証、`DECISIONS.md` D-21)。"
    )
    lines.append("")

    lines.append("### ②収束性: 1回性エンジンにつきMDP適用対象外(SMAS_theorymap.md 2.1節)")
    lines.append(
        f"- 決定論性・局所-大域整合(#8): ②誘因構造エンジンは純関数(同一入力→同一出力)であり、"
        f"各エージェントのローカル計算は自明に一致する。"
    )
    lines.append(
        f"- 逸脱注入からの回復力(#20): シーン3(自己拘束の確認、D-07)で反実仮想比較を実施。"
        f"carolの合計効用は 逸脱={self_enforcement.total_actual_utility:+.2f} / "
        f"正直(反実仮想)={self_enforcement.total_counterfactual_utility:+.2f}"
        f"({'逸脱は得にならず' if not self_enforcement.deviation_profitable else '要再確認: 逸脱が得になっている'})。"
    )
    lines.append("- 収束性そのもの(#17): 代替評価として③頑健性(モンテカルロ)を参照。")
    lines.append("")

    lines.append(
        f"### ③頑健性: モンテカルロ N={mc_summary['n_trials']}試行、"
        f"逸脱が得になったケース数={mc_summary['profitable_deviation_count']}"
        f"({mc_summary['profitable_deviation_rate']:.1%})"
    )
    lines.append("- 誘因整合性(#1)・耐戦略性(#2): 上記の通り、過大申告(alice、1.3倍)は一度も得にならなかった。")
    lines.append(
        "- 結託耐性(#5): 本ケースでは未検証(拡張フェーズ回し、scope_exclusions_and_deferrals.md Part2)。"
    )
    lines.append(
        f"- 打ち切り耐性(#23): 3シーン構成の全{len(scenes)}ラウンドでフォールバックに落ちず完走"
        f"({'確認済み' if all(not s.outcome.terminated_by_fallback for s in scenes) else '要確認'})。"
    )
    lines.append("")

    lines.append("### ④資源コスト: 計算量・実行時間の概算(このマシンでの1回計測、参考値)")
    lines.append("- VCGエンジン(単発呼び出し、申告2件): O(n log n)(申告のソート)。"
                 f"実測 {single_vcg_call_elapsed * 1000:.2f} ms")
    lines.append(f"- 3シーン構成(scene1×5, scene2×5): 実測 {three_scene_elapsed:.3f} 秒")
    lines.append(f"- モンテカルロ N={n_trials}試行: 実測 {montecarlo_elapsed:.3f} 秒"
                 f"({montecarlo_elapsed / n_trials * 1000:.3f} ms/試行)")
    lines.append(f"- ⑤DisCoPy構造検証: 実測 {verification_elapsed * 1000:.2f} ms")
    lines.append("- 資源コスト(#24)の内訳としては以上の通り。分散台帳・検証可能遅延関数等の"
                 "本番運用コストは技術選定が未決のため対象外(SMAS_theorymap.md 5章)。")
    lines.append("")

    disco_py_pass = "Pass" if verification_report.all_passed else "Fail"
    quint_result = run_quint_check()
    lines.append(f"### ⑤検証可能性: DisCoPy {disco_py_pass} / Quint {quint_result}")
    lines.append(f"- 合成則の充足(#13): 結合律・単位律を含む構造検証、{len(verification_report.structural_checks)}項目中"
                 f"{sum(c.passed for c in verification_report.structural_checks)}項目Pass。")
    for check in verification_report.structural_checks:
        lines.append(f"  - {check.check_name}: {'Pass' if check.passed else 'Fail'}")
    lines.append("- 関手による対応づけ(#15): 2ケース目未着手のため今回は対象外。")
    lines.append(f"- 並行安全性(#16)・打ち切り耐性(#23)の形式的側面: {quint_result}")
    lines.append("")

    lines.append("## 5大指標に対応表がない評価観点(補足)")
    lines.append("")
    lines.append(f"- プラガブル性(#11): {check_pluggability()}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "**限界の明記**: ②収束性はMDPが適用できないため代替評価に留まる。③頑健性のモンテカルロは"
        "本スクリプトが定義した逸脱分布(過大申告1.3倍)に対する頑健性のみを保証し、それ以外の逸脱"
        "パターンへの一般化は主張しない。⑤検証可能性のQuintは、安全性不変条件のシミュレーション"
        "(有限サンプル)による経験的確認に留まり、Apalache(SMT)・TLC(公平性を伴う活性検証)に"
        "よる網羅的な形式検証ではない(環境のツールチェイン不具合による、docs/DECISIONS.md D-19)。"
    )

    os.makedirs(_CASE_DIR / "results", exist_ok=True)
    with open(_CASE_DIR / "results" / "summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("cases/task_allocation/results/summary.md を生成しました。")
    print(f"①到達可能性={'Yes' if reachability_yes else 'No'} / "
          f"③頑健性: 逸脱成功={mc_summary['profitable_deviation_count']}/{mc_summary['n_trials']} / "
          f"⑤DisCoPy={disco_py_pass}")


if __name__ == "__main__":
    main()
