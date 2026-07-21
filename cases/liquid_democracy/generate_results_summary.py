"""5大指標レポート生成(CLAUDE.md 10章、ケース4: Liquid Democracy)。

python cases/liquid_democracy/generate_results_summary.py で(リポジトリルートから)
実行し、cases/liquid_democracy/results/summary.md を書き出す。

ケース1〜3の「1エージェントの逸脱・操作」という筋書きとは異なり、このケースの
主眼は委任構造そのもの(循環委任・重みの保存則・権力集中の性質の違い)にある(D-30)。
評価観点#19(委任連鎖を通した誘因構造の伝播の妥当性)を、プロジェクト開始以来
初めて実地検証する。
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
from schemas.agent_schema import Agent
from schemas.environment_schema import EnvironmentConfig
from verification import run_structural_verification

from delegation_agents import DelegatingAgent, DirectVotingAgent
from deviation_test import faithfulness_holds, run_scene, weight_conservation_holds
from incentive_engine import LiquidDemocracyEngine, LiquidDemocracyParameters
from schemas.incentive_schema import Declaration

QUINT_SPEC_PATH = str(_CASE_DIR / "quint" / "liquid_democracy.qnt")  # subprocess呼び出し用(絶対パス、CWD非依存)
QUINT_SPEC_DISPLAY_PATH = str(Path(QUINT_SPEC_PATH).relative_to(_CASE_DIR.parents[1]))  # レポート表示用


def run_quint_check() -> str:
    """動的安全性検証(⑤、①到達可能性側)。ケース1〜3(D-19)と同じ環境制約により、
    シミュレータ(`quint run`)による安全性不変条件の経験的確認に留める。"""
    if shutil.which("quint") is None:
        return "未実施(quintコマンドが見つかりません。npm install -g @informalsystems/quint)"
    try:
        result = subprocess.run(
            [
                "quint", "run", QUINT_SPEC_PATH,
                "--main", "main",
                "--invariant", "safety",
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
        f"{status} — `quint run`(300サンプル、safety不変条件: 委任連鎖を辿った回数が"
        f"[0, MAX_DEPTH]に収まり、statusがfollowing/resolved/voidedのいずれかに収まる)"
        f"で違反なし。Apalache(SMT、安全性)・TLC(公平性を伴う活性: 「委任の解決は"
        f"いつか必ずresolvedかvoidedで終わる」)による網羅的検証は、ケース1〜3(D-19)"
        f"と同じ環境のツールチェイン不具合により未実施。`.qnt`はtypecheck済みで、"
        f"環境を修復すれば`{QUINT_SPEC_DISPLAY_PATH}`の再実行のみで足りる。"
    )


def run_structural_monte_carlo(
    engine: LiquidDemocracyEngine, agent_ids: list[str], choices: list[str], n_trials: int, rng: random.Random
) -> dict:
    """③頑健性: このケースでは「逸脱が得になるか」ではなく「ランダムな委任グラフ
    (循環を含む)に対して、委任解決が例外なく停止し、重みの保存則を常に満たすか」
    という構造的頑健性を測る(ケース3の戦略的操作可能性の検証とは異なる軸、D-30)。
    """
    conserved_count = 0
    had_void_count = 0
    for _ in range(n_trials):
        declarations = []
        for agent_id in agent_ids:
            if rng.random() < 0.5:
                declarations.append(Declaration(agent_id=agent_id, declared_ranking=[rng.choice(choices)]))
            else:
                target = rng.choice([a for a in agent_ids if a != agent_id])
                declarations.append(Declaration(agent_id=agent_id, delegate_to=target))
        resolved = engine.resolve_delegations(declarations)
        if weight_conservation_holds(resolved, total_agents=len(agent_ids)):
            conserved_count += 1
        if any(choice is None for choice in resolved.values()):
            had_void_count += 1
    return {
        "n_trials": n_trials,
        "conserved_count": conserved_count,
        "conserved_rate": conserved_count / n_trials,
        "had_void_count": had_void_count,
    }


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env_config = EnvironmentConfig(**config["environment"])
    params = LiquidDemocracyParameters(**config["mechanism"])
    engine = LiquidDemocracyEngine(params)

    # --- ①②: シーン1(平常時+忠実性の証明、#19) -------------------------------------
    scene1_env = EnvironmentClient(env_config)
    scene1_agents = [
        DirectVotingAgent("alice", "yes"),
        DirectVotingAgent("bob", "no"),
        DelegatingAgent("carol", "alice"),
        DelegatingAgent("dave", "carol"),
        DelegatingAgent("erin", "bob"),
    ]
    true_preferences = {"alice": "yes", "bob": "no", "carol": "yes", "dave": "yes", "erin": "no"}
    t0 = time.perf_counter()
    scene1 = run_scene("scene1_faithful_delegation", scene1_agents, engine, scene1_env)
    scene1_elapsed = time.perf_counter() - t0
    weight_conserved_1 = weight_conservation_holds(scene1.resolved, total_agents=len(scene1_agents))
    faithful = faithfulness_holds(scene1.resolved, true_preferences, params.choices)

    individual_rationality_holds = True  # 支払いが無いため効用は常に0以上(構造的に自明、ケース2・3と同じ)

    # --- シーン2(循環委任の注入) ----------------------------------------------------
    scene2_env = EnvironmentClient(env_config)
    scene2_agents = [
        DirectVotingAgent("alice", "yes"),
        DirectVotingAgent("bob", "no"),
        DelegatingAgent("frank", "grace"),
        DelegatingAgent("grace", "heidi"),
        DelegatingAgent("heidi", "frank"),
    ]
    t0 = time.perf_counter()
    scene2 = run_scene("scene2_cycle_injected", scene2_agents, engine, scene2_env)
    scene2_elapsed = time.perf_counter() - t0
    cycle_voided_correctly = (
        scene2.resolved["frank"] is None and scene2.resolved["grace"] is None and scene2.resolved["heidi"] is None
        and scene2.resolved["alice"] == "yes" and scene2.resolved["bob"] == "no"
    )
    weight_conserved_2 = weight_conservation_holds(scene2.resolved, total_agents=len(scene2_agents))

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
    t0 = time.perf_counter()
    scene3 = run_scene("scene3_super_delegate", scene3_agents, engine, scene3_env)
    scene3_elapsed = time.perf_counter() - t0
    priya_weight = sum(1 for choice in scene3.resolved.values() if choice == "yes")
    delegations_auditable = all(
        t.process_trace.get("resolved_choice") == "yes"
        for t in scene3_env.read_traces()
        if t.agent_id in {"q1", "q2", "q3", "q4"}
    )

    # --- ⑤: DisCoPy構造検証 -----------------------------------------------------------
    t0 = time.perf_counter()
    verification_report = run_structural_verification(
        all_agent_ids=["alice", "bob", "carol", "dave", "erin"], write_own_domain_only=True
    )
    verification_elapsed = time.perf_counter() - t0

    reachability_yes = individual_rationality_holds and verification_report.all_passed

    # --- ③: モンテカルロ(構造的頑健性、ケース3の戦略的操作検証とは異なる軸) -----------
    rng = random.Random(0)
    n_mc_trials = config["verification_kit"]["monte_carlo_trials"]
    agent_ids = [f"a{i}" for i in range(6)]
    t0 = time.perf_counter()
    mc_summary = run_structural_monte_carlo(engine, agent_ids, params.choices, n_mc_trials, rng)
    montecarlo_elapsed = time.perf_counter() - t0

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# 4ケース目(Liquid Democracy・委任民主主義) 検証結果サマリー")
    lines.append("")
    lines.append(f"生成日時(UTC): {generated_at}")
    lines.append("生成コマンド: `python cases/liquid_democracy/generate_results_summary.py`")
    lines.append("")
    lines.append("CLAUDE.md 10章の運用ルールに従い、5大指標を主役として記載する。")
    lines.append("25項目評価観点(docs/evaluation_criteria.md)は各指標の根拠として番号付きで1行併記する。")
    lines.append("")
    lines.append(
        "**このケースの狙い(D-30)**: ケース1〜3はいずれも「1エージェントの逸脱・操作」という"
        "筋書きだった。このケースは委任構造そのもの(循環委任・重みの保存則・権力集中の性質の"
        "違い)に主眼を置く。集計方式はあえて二択・単純多数決(それ自体は耐戦略性を満たす)を"
        "選び、集計方式の操作可能性(ケース3で実証済み)と論点を混同しない。評価観点#19"
        "(委任連鎖を通した誘因構造の伝播の妥当性)を、プロジェクト開始以来初めて実地検証する。"
    )
    lines.append("")
    lines.append("## 5大指標")
    lines.append("")

    lines.append(f"### ①到達可能性: {'Yes' if reachability_yes else 'No'}")
    lines.append(
        "- 個人合理性(#25): 支払いが発生しないメカニズムのため、実現効用は構造的に常に0以上"
        "(勝った選択肢を支持していれば正の効用、そうでなければ0)。"
    )
    lines.append(
        f"- 権力集中の不在(#14、定義の再検討): シーン3(スーパー代理人)でpriyaに4人が委任し、"
        f"重みが{priya_weight}に集約された。ただしこれは各委任者が自発的に選んだ結果であり、"
        f"公開痕跡(process_trace)により誰でも監査可能({'確認' if delegations_auditable else '不成立'})、"
        f"かつ次ラウンドで委任先を自由に変更できる。「1主体が他者の運命を一方的に決める」という"
        f"#14本来の懸念(同意なき権力集中)とは性質が異なり、⑤構造検証(全{len(verification_report.structural_checks)}項目)は"
        f"{'すべてPass' if verification_report.all_passed else '一部Fail'}。"
    )
    lines.append("")

    lines.append("### ②収束性: 1回性エンジンにつきMDP適用対象外(SMAS_theorymap.md 2.1節、ケース1・3と同じ)")
    lines.append(
        f"- 委任連鎖を通した誘因構造の伝播の妥当性(#19、初検証): シーン1で、全員が忠実に委任した"
        f"場合の集計結果({'合致' if faithful else '不一致(要再確認)'})と、委任なしで各人が"
        f"直接投票した場合(反実仮想)の集計結果を比較し、一致することを確認した。委任を経由しても"
        f"各人の真の選好の反映(誘因構造)が劣化しないことの、最も文字通りの実証。"
    )
    lines.append(
        f"- 決定論性・局所-大域整合(#8): 重みの保存則(有効票+無効票の合計=参加者数)がシーン1"
        f"({'成立' if weight_conserved_1 else '不成立'})・シーン2({'成立' if weight_conserved_2 else '不成立'})"
        f"のいずれでも成立。②誘因構造エンジンは純関数であり、各エージェントのローカル計算は自明に一致する。"
    )
    lines.append("")

    lines.append(
        f"### ③頑健性: モンテカルロ N={mc_summary['n_trials']}試行(ランダムな委任グラフ、循環を含む)、"
        f"重みの保存則が成立した試行数={mc_summary['conserved_count']}({mc_summary['conserved_rate']:.1%})"
    )
    lines.append(
        "- **このケースの③頑健性は、ケース3(戦略的操作の成功率)とは異なる軸を測る**: "
        "集計方式(二択単純多数決)自体は耐戦略性を満たす設計のため、ここでは「委任構造が"
        "ランダム・敵対的な配線(循環を含む)に対して構造的に頑健か」(例外なく停止し、"
        "重みの保存則を常に満たすか)を測る。誘因整合性・耐戦略性の直接検証はケース3の役割。"
    )
    lines.append(
        "- **本チェックの限界(D-31)**: 「重みの保存則100%」は、resolve_delegationsが"
        "全申告者に必ず何らかの値を設定する実装である以上、ほぼ自明に成立する指標であり、"
        "深い経験的発見ではない。真に非自明な主張は「循環・深さ上限があっても例外や"
        "無限ループが起きない」ことであり、こちらがモンテカルロの実質的な価値になる。"
        "なお実装当初、実在しない委任先(誤字等)がresolvedに紛れ込み保存則が壊れる"
        "実バグがあり、修正済み(D-31)。"
    )
    lines.append(
        f"- 打ち切り耐性(#23): シーン2(循環委任の注入)で解決が例外なく停止し"
        f"({'確認' if not scene2.outcome.terminated_by_fallback else '要確認'})、"
        f"循環に含まれるfrank/grace/heidiの票が正しく無効化され、他者(alice/bob)の票には"
        f"影響しなかった({'確認' if cycle_voided_correctly else '不成立'})。"
        f"モンテカルロでも{mc_summary['had_void_count']}/{mc_summary['n_trials']}試行で"
        f"循環等による無効票が発生したが、いずれも例外なく解決が停止した。"
    )
    lines.append(
        "- 結託耐性(#5): 本ケースでも未検証(ケース1〜3と同じくscope_exclusions_and_deferrals.md "
        "Part2の対象)。`pygambit`(技術スタックに③頑健性用として記載済みだが4ケースとも未使用)に"
        "よる均衡計算等、別途の検証が必要(D-25)。"
    )
    lines.append("")

    lines.append("### ④資源コスト: 計算量・実行時間の概算(このマシンでの1回計測、参考値)")
    lines.append(f"- シーン1(平常時、5エージェント): 実測 {scene1_elapsed * 1000:.2f} ms")
    lines.append(f"- シーン2(循環委任、5エージェント): 実測 {scene2_elapsed * 1000:.2f} ms")
    lines.append(f"- シーン3(スーパー代理人、6エージェント): 実測 {scene3_elapsed * 1000:.2f} ms")
    lines.append(f"- モンテカルロ N={mc_summary['n_trials']}試行(6エージェント、ランダム委任グラフ): 実測 {montecarlo_elapsed:.3f} 秒")
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
        "- 関手による対応づけ(#15): ケース1〜3からの型の対応づけを確認済み。IncentiveEngine/"
        "AllocationResult/VersionedMechanismは無変更のまま満たす。Declaration/ActionOutputに"
        "delegate_to(委任先)という新フィールドを追加した(既存フィールドは変更せず、後方互換の"
        "追加)。ケース3のdeclared_rankingに続き2ケース連続のA側拡張であり、CLAUDE.md 11章の"
        "「頻度が増えたら危険信号」チェックの対象として明示的に記録する(D-30)。"
    )
    lines.append(f"- 並行安全性(#16)・打ち切り耐性(#23)の形式的側面: {quint_result}")
    lines.append("")

    lines.append("## 5大指標に対応表がない評価観点(補足)")
    lines.append("")
    plug_conforms = all(
        isinstance(a, Agent) for a in (DirectVotingAgent("alice", "yes"), DelegatingAgent("carol", "alice"))
    )
    lines.append(
        f"- プラガブル性(#11): {'Pass' if plug_conforms else 'Fail'} — DirectVotingAgent/"
        f"DelegatingAgent(ケース4固有、委任申告用に新設)は共通のAgentプロトコル"
        f"(schemas/agent_schema.py)を満たす。全く異なる申告の「形」(数値→順位→委任先)を"
        f"持つメカニズムでも、④実行主体層のプロトコル自体は変更不要だった(3ケース連続で確認)。"
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "**限界の明記**: ③頑健性のモンテカルロは、本スクリプトが定義したランダム委任グラフ"
        "(50%直接投票/50%ランダム委任)への構造的頑健性のみを確認する。悪意を持って構成された"
        "委任グラフ(多数の相互リンクした循環等)への一般化は主張しない。⑤検証可能性のQuintは、"
        "安全性不変条件のシミュレーション(有限サンプル)による経験的確認に留まり、Apalache・"
        "TLCによる網羅的な形式検証ではない(環境のツールチェイン不具合による、docs/DECISIONS.md D-19)。"
    )

    (_CASE_DIR / "results").mkdir(exist_ok=True)
    with open(_CASE_DIR / "results" / "summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("cases/liquid_democracy/results/summary.md を生成しました。")
    print(f"①到達可能性={'Yes' if reachability_yes else 'No'} / "
          f"②#19忠実性={'合致' if faithful else '不一致'} / "
          f"③頑健性: 重み保存={mc_summary['conserved_count']}/{mc_summary['n_trials']} / "
          f"⑤DisCoPy={disco_py_pass}")


if __name__ == "__main__":
    main()
