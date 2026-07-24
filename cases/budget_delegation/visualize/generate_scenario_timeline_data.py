"""cases/budget_delegation/visualize/scenario_timeline.html に埋め込む、
3シーン構成の推移データを機械的に生成するビルドスクリプト(D-41/D-52/D-57/D-60の
パターンをケース6に展開)。

python cases/budget_delegation/visualize/generate_scenario_timeline_data.py で
(リポジトリルートから)実行する。

シーン1(平常時、3ラウンド、booking→transportへの委任額=2000円)→シーン2
(合成リスク注入、3ラウンド、bookingの委任額だけを10000円に変更、D-78)の
6ラウンドを、「transportの手元決済余地(円)」(上)と「決済余地の超過分・
実際vs反実仮想(元の2000円に戻した場合)」(下)として再生する。
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
from schemas.incentive_schema import Declaration

from incentive_engine import PartialDelegationEngine, PartialDelegationParameters
from deviation_test import run_three_scene_demo
from delegation_agents import BudgetDelegatingAgent


def compute_three_scene_demo(config: dict) -> dict:
    params = PartialDelegationParameters(**config["mechanism"])
    engine = PartialDelegationEngine(params)
    env_config = EnvironmentConfig(**config["environment"])
    env = EnvironmentClient(env_config)

    injected_agent_id = "booking"
    injected_delegate_to = "transport"
    injected_declared_value = 10000.0
    baseline_declared_value = 2000.0

    baseline_agents = [
        BudgetDelegatingAgent("me", "booking", 45000.0),
        BudgetDelegatingAgent("booking", "transport", baseline_declared_value),
        BudgetDelegatingAgent("transport", None),
        BudgetDelegatingAgent("dining", None),
    ]

    scenes, report = run_three_scene_demo(
        baseline_agents,
        injected_agent_id=injected_agent_id,
        injected_delegate_to=injected_delegate_to,
        injected_declared_value=injected_declared_value,
        baseline_declared_value=baseline_declared_value,
        engine=engine,
        env=env,
        scene1_rounds=3,
        scene2_rounds=3,
    )

    intended_max = params.intended_max_budget["transport"]

    top_actual, won_actual, util_actual, util_cf = [], [], [], []
    for scene_result in scenes:
        held_actual = scene_result.held["transport"]
        top_actual.append(round(held_actual, 2))
        won_actual.append(held_actual > intended_max + 1e-9)

        counterfactual_declarations = [
            Declaration(
                agent_id=d.agent_id,
                delegate_to=d.delegate_to,
                declared_value=(
                    baseline_declared_value
                    if d.agent_id == injected_agent_id and d.delegate_to == injected_delegate_to
                    else d.declared_value
                ),
            )
            for d in scene_result.declarations
        ]
        held_cf = engine.resolve_reachable_budgets(counterfactual_declarations)["transport"]
        util_actual.append(round(max(0.0, held_actual - intended_max), 2))
        util_cf.append(round(max(0.0, held_cf - intended_max), 2))

    return {
        "label": "3シーンデモ(合成リスク注入 vs 反実仮想)",
        "hasCounterfactual": True,
        "scenes": [
            {"name": "scene1_baseline", "label": "平常時", "rounds": [1, 3], "color": "var(--scene-build)"},
            {"name": "scene2_budget_injected", "label": "合成リスク注入(1件の委任額変更)",
             "rounds": [4, 6], "color": "var(--scene-deviate)"},
        ],
        "N": 6,
        "topChartLabel": "transportの手元決済余地(円)",
        "topSeriesActual": top_actual,
        "wonActual": won_actual,
        "utilActual": util_actual,
        "utilCf": util_cf,
        "verdictText": (
            "誰も虚偽申告していないのに想定外の決済余地が発生する(D-78/D-80): シーン2でbookingの"
            "1件の委任額変更(transportへの2000円→10000円、単独では「念のため多めに」という"
            "局所的に正当な判断)を加えると、既存の委任構造(me→booking→transport)と合成され、"
            "transportの手元決済余地が本来の用途(2000円)を大きく超える(10000円、超過分8000円)。"
            "その1件を元に戻せば超過分は完全に消える(反実仮想=0円)——単一の委任額変更(root cause)"
            "が全体の脆弱性を決めている、ケース5(IAM委任チェーン)とは異なる「金額の合成」による"
            "confused deputyの実例。"
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
