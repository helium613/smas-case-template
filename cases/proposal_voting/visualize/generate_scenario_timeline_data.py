"""cases/proposal_voting/visualize/scenario_timeline.html に埋め込む、
2シーン構成の推移データを機械的に生成するビルドスクリプト(D-41/D-52/D-57の
パターンをケース3に展開、Task #13)。

python cases/proposal_voting/visualize/generate_scenario_timeline_data.py で
(リポジトリルートから)実行する。

シーン1(平常時、5ラウンド、全員honest)→シーン2(逸脱注入、5ラウンド、
bobがBuryingStrategicAgentに差し替わる、D-27)の10ラウンドを、
「bobの真の2位候補(proposal_a)を、bobが自分の申告の何位に置いたか」(上、
1位=正直、4位=完全に埋葬)と累積効用・実際vs反実仮想(下)として再生する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CASE_DIR = Path(__file__).resolve().parent.parent
_HTML_PATH = Path(__file__).resolve().parent / "scenario_timeline.html"
_START_MARKER = "/* SCENARIOS_DATA_START (generate_scenario_timeline_data.py が機械的に更新する、手編集禁止) */"
_END_MARKER = "/* SCENARIOS_DATA_END */"

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_CASE_DIR))

from environment import EnvironmentClient
from schemas.environment_schema import EnvironmentConfig

from incentive_engine import BordaVotingEngine, BordaVotingParameters
from deviation_test import run_two_scene_demo
from voting_agents import BuryingStrategicAgent, HonestVotingAgent


def compute_two_scene_demo(config: dict) -> dict:
    env_config = EnvironmentConfig(**config["environment"])
    candidate_ids = config["mechanism"]["candidate_ids"]
    proposal_a, proposal_b, proposal_c, proposal_d = candidate_ids
    engine = BordaVotingEngine(BordaVotingParameters(candidate_ids=candidate_ids))
    scenario = config["scenario"]

    # generate_results_summary.pyの具体例(D-27)と同じ真の評価額。
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
    scenes, report = run_two_scene_demo(
        honest_agents, manipulating_agent_id="bob", manipulating_agent_factory=make_burying,
        manipulating_agent_true_values=bob_true, engine=engine, env=env,
        scene1_rounds=scenario["scene1_rounds"], scene2_rounds=scenario["scene2_rounds"],
    )

    true_second_place = HonestVotingAgent("bob", bob_true).true_ranking()[1]  # = proposal_a

    bury_position, won_actual, util_actual, util_cf = [], [], [], []
    cumulative_actual = 0.0
    cumulative_cf = 0.0
    round_comparison_by_index = {i: rc for i, rc in enumerate(report.rounds)}
    for i, scene_result in enumerate(scenes):
        bob_decl = next(d for d in scene_result.declarations if d.agent_id == "bob")
        position = bob_decl.declared_ranking.index(true_second_place) + 1  # 1-indexed
        winner = scene_result.outcome.result.allocated_agent_ids[0] if scene_result.outcome.result else None
        won_actual.append(winner == proposal_b)
        bury_position.append(position)

        if scene_result.name == "scene1_honest":
            # シーン1はbobが正直なため、実際=反実仮想(差が生まれない)。
            round_utility = bob_true.get(winner, 0.0)
            cumulative_actual += round_utility
            cumulative_cf += round_utility
        else:
            scene2_index = i - scenario["scene1_rounds"]
            rc = round_comparison_by_index[scene2_index]
            cumulative_actual += rc.actual_utility
            cumulative_cf += rc.counterfactual_utility
        util_actual.append(round(cumulative_actual, 3))
        util_cf.append(round(cumulative_cf, 3))

    return {
        "label": "2シーンデモ(埋葬戦術 vs 反実仮想honest)",
        "hasCounterfactual": True,
        "scenes": [
            {"name": "scene1_honest", "label": "平常時",
             "rounds": [1, scenario["scene1_rounds"]], "color": "var(--scene-build)"},
            {"name": "scene2_manipulation_injected", "label": "逸脱注入(埋葬戦術)",
             "rounds": [scenario["scene1_rounds"] + 1, scenario["scene1_rounds"] + scenario["scene2_rounds"]],
             "color": "var(--scene-deviate)"},
        ],
        "N": scenario["scene1_rounds"] + scenario["scene2_rounds"],
        "topChartLabel": f"bobの申告順位における{true_second_place}(真の2位)の位置",
        "topSeriesActual": bury_position,
        "wonActual": won_actual,
        "utilActual": util_actual,
        "utilCf": util_cf,
        "verdictText": (
            f"埋葬戦術は得になる(理論どおりの想定内の結果、D-27): シーン2の合計効用"
            f"(実際={report.total_actual_utility:+.2f})は、正直申告を貫いた場合(反実仮想="
            f"{report.total_counterfactual_utility:+.2f})を明確に上回る——ボルダ得点は"
            f"非耐戦略性メカニズムであり、真の2位候補を最下位に落とす単純な固定ルール"
            f"だけで得をする、意図的に選んだ「悪い設計」の実例。"
        ),
    }


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    scenarios = {"two_scene_demo": compute_two_scene_demo(config)}

    block = (
        f"{_START_MARKER}\n  var SCENARIOS = "
        + json.dumps(scenarios, ensure_ascii=False, indent=2)
        + f";\n  {_END_MARKER}"
    )

    html = _HTML_PATH.read_text(encoding="utf-8")
    start_idx = html.find(_START_MARKER)
    end_idx = html.find(_END_MARKER)
    if start_idx == -1 or end_idx == -1:
        raise RuntimeError(f"マーカーが見つかりません: {_HTML_PATH} に {_START_MARKER} を追加してください")
    end_idx += len(_END_MARKER)
    new_html = html[:start_idx] + block + html[end_idx:]
    _HTML_PATH.write_text(new_html, encoding="utf-8")
    print(f"{_HTML_PATH} のSCENARIOSデータを更新しました。")


if __name__ == "__main__":
    main()
