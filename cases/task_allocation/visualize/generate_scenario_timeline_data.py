"""cases/task_allocation/visualize/scenario_timeline.html に埋め込む、
3シーン構成の推移データを機械的に生成するビルドスクリプト(D-41/D-52/D-57の
パターンをケース1に展開、Task #13)。

python cases/task_allocation/visualize/generate_scenario_timeline_data.py で
(リポジトリルートから)実行する。

シーン1(平常時、5ラウンド、全員honest)→シーン2(逸脱注入、5ラウンド、
carolがGreedyOverstatingAgentに差し替わる)の10ラウンドを、carolの申告値
(上)と累積効用・実際vs反実仮想(下)として再生する。D-07の設計どおり、
シーン3(自己拘束の確認)は追加のラウンドではなく、シーン2の各ラウンドに
ついて「もし全員honestだったら」を計測しただけの反実仮想比較であることに
注意(deviation_test.pyのSelfEnforcementReport)。
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

from aggregation import TerminationConfig
from agents.rule_based import FluctuatingHonestAgent, GreedyOverstatingAgent
from environment import EnvironmentClient
from schemas.environment_schema import EnvironmentConfig
from incentive_engine import SingleItemVcgEngine, SingleItemVcgParameters
from deviation_test import run_three_scene_demo


def compute_three_scene_demo(config: dict) -> dict:
    env_config = EnvironmentConfig(**config["environment"])
    engine = SingleItemVcgEngine(SingleItemVcgParameters(reserve_price=0.0))
    termination = TerminationConfig(**config["aggregation"])
    agent_ids = ["alice", "bob", "carol"]
    scene1_rounds, scene2_rounds = 5, 5

    env = EnvironmentClient(env_config)
    honest_agents = [
        FluctuatingHonestAgent(agent_id, index, n_agents=len(agent_ids))
        for index, agent_id in enumerate(agent_ids)
    ]

    def make_greedy_deviant(agent):
        return GreedyOverstatingAgent(agent.agent_id, fixed_declared_value=1000.0)

    scenes, report = run_three_scene_demo(
        honest_agents, deviating_agent_id="carol", deviating_agent_factory=make_greedy_deviant,
        engine=engine, env=env, scene1_rounds=scene1_rounds, scene2_rounds=scene2_rounds,
        termination=termination,
    )

    true_value_schedule = FluctuatingHonestAgent("carol", agent_ids.index("carol"), n_agents=len(agent_ids))

    declared_actual, won_actual, util_actual, util_cf = [], [], [], []
    cumulative_actual = 0.0
    cumulative_cf = 0.0
    round_comparison_by_index = {i: rc for i, rc in enumerate(report.rounds)}  # シーン2の各ラウンド(0-indexed)
    for i, scene_result in enumerate(scenes):
        carol_decl = next(d for d in scene_result.declarations if d.agent_id == "carol")
        won = scene_result.outcome.result is not None and "carol" in scene_result.outcome.result.allocated_agent_ids
        declared_actual.append(round(carol_decl.declared_value, 3))
        won_actual.append(bool(won))

        if scene_result.name == "scene1_honest":
            # シーン1はcarolが正直なため、実際=反実仮想(差が生まれない)。
            true_value = true_value_schedule.true_value_for_round(i + 1)
            round_utility = true_value if won else 0.0
            cumulative_actual += round_utility
            cumulative_cf += round_utility
        else:
            scene2_index = i - scene1_rounds
            rc = round_comparison_by_index[scene2_index]
            cumulative_actual += rc.actual_utility
            cumulative_cf += rc.counterfactual_utility
        util_actual.append(round(cumulative_actual, 3))
        util_cf.append(round(cumulative_cf, 3))

    return {
        "label": "3シーンデモ(逸脱 vs 反実仮想honest)",
        "hasCounterfactual": True,
        "scenes": [
            {"name": "scene1_honest", "label": "平常時",
             "rounds": [1, scene1_rounds], "color": "var(--scene-build)"},
            {"name": "scene2_deviation_injected", "label": "逸脱注入(過大申告)",
             "rounds": [scene1_rounds + 1, scene1_rounds + scene2_rounds], "color": "var(--scene-deviate)"},
        ],
        "N": scene1_rounds + scene2_rounds,
        "topChartLabel": "carolの申告値",
        "topSeriesActual": declared_actual,
        "topSeriesRef": None,
        "topSeriesRefLabel": None,
        "wonActual": won_actual,
        "utilActual": util_actual,
        "utilCf": util_cf,
        "verdictText": (
            f"逸脱(固定高値1000.0の申告)は得にならない: シーン2の合計効用"
            f"(実際={report.total_actual_utility:+.2f})は、正直申告を貫いた場合(反実仮想="
            f"{report.total_counterfactual_utility:+.2f})を上回らない——VCGの支払い構造"
            f"(勝てば第2価格を支払う)により、過大申告で勝利を拡張しても、支払いの増加が"
            f"利得を相殺する(D-07)。"
        ),
    }


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    scenarios = {"three_scene_demo": compute_three_scene_demo(config)}

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
