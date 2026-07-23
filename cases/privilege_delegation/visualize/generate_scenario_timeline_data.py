"""cases/privilege_delegation/visualize/scenario_timeline.html に埋め込む、
3シーン構成の推移データを機械的に生成するビルドスクリプト(D-41/D-52/D-57/D-58の
パターンをケース5に展開)。

python cases/privilege_delegation/visualize/generate_scenario_timeline_data.py で
(リポジトリルートから)実行する。

シーン1(平常時、3ラウンド、admin.delegate_to=None)→シーン2(合成リスク注入、
3ラウンド、adminのtrust宣言を1件追加)の6ラウンドを、build_svcの到達可能tier
(上)と昇格したエージェント数・実際vs反実仮想(下)として再生する。D-60の設計
どおり、シーン3(根本原因の特定)は追加のラウンドではなく、シーン2の各ラウンドに
ついて「注入した1件のtrust宣言が無かったら」を計測しただけの反実仮想比較である
ことに注意(deviation_test.pyのEscalationReportと同じ考え方を、ラウンドごとに
展開したもの)。
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

from delegation_agents import TrustDeclaringAgent
from deviation_test import run_three_scene_demo
from incentive_engine import PrivilegeDelegationEngine, PrivilegeDelegationParameters


def compute_three_scene_demo(config: dict) -> dict:
    env_config = EnvironmentConfig(**config["environment"])
    params = PrivilegeDelegationParameters(**config["mechanism"])
    engine = PrivilegeDelegationEngine(params)

    baseline_agents = [
        TrustDeclaringAgent("admin", None),
        TrustDeclaringAgent("deploy_svc", "ci_svc"),
        TrustDeclaringAgent("ci_svc", "build_svc"),
        TrustDeclaringAgent("build_svc", None),
        TrustDeclaringAgent("intern_svc", None),
    ]
    scene1_rounds, scene2_rounds = 3, 3

    env = EnvironmentClient(env_config)
    scenes, esc_report = run_three_scene_demo(
        baseline_agents, injected_agent_id="admin", injected_delegate_to="ci_svc",
        engine=engine, env=env, scene1_rounds=scene1_rounds, scene2_rounds=scene2_rounds,
    )

    reachable_actual: list[int] = []
    escalated_count_actual: list[int] = []
    escalated_count_cf: list[int] = []
    for scene_result in scenes:
        reachable_actual.append(scene_result.reachable["build_svc"])
        actual_escalated = scene_result.outcome.result.allocated_agent_ids if scene_result.outcome.result else []
        escalated_count_actual.append(len(actual_escalated))

        if scene_result.name == "scene1_baseline":
            # シーン1はまだ注入前のため、実際=反実仮想(差が生まれない)。
            escalated_count_cf.append(len(actual_escalated))
        else:
            # シーン3(計測): 注入した1件(admin→ci_svc)だけを取り除いた場合の
            # 昇格数を、メカニズムを介さず直接計算する(環境への書き込みは行わない)。
            cf_declarations = [
                Declaration(agent_id=d.agent_id, delegate_to=(None if d.agent_id == "admin" else d.delegate_to))
                for d in scene_result.declarations
            ]
            cf_outcome = engine.allocate_and_pay(cf_declarations)
            escalated_count_cf.append(len(cf_outcome.allocated_agent_ids))

    return {
        "label": "3シーンデモ(合成リスク注入 vs 反実仮想)",
        "hasCounterfactual": True,
        "scenes": [
            {"name": "scene1_baseline", "label": "平常時",
             "rounds": [1, scene1_rounds], "color": "var(--scene-build)"},
            {"name": "scene2_trust_injected", "label": "合成リスク注入(1件のtrust宣言追加)",
             "rounds": [scene1_rounds + 1, scene1_rounds + scene2_rounds], "color": "var(--scene-deviate)"},
        ],
        "N": scene1_rounds + scene2_rounds,
        "topChartLabel": "build_svcの到達可能tier",
        "topSeriesActual": reachable_actual,
        "topSeriesRef": params.intended_max_tier["build_svc"],
        "topSeriesRefLabel": "意図された上限(intended_max_tier)",
        "wonActual": [c > 0 for c in escalated_count_actual],
        "wonLabel": "権限昇格の発生?",
        "wonGoodValue": False,
        "utilActual": escalated_count_actual,
        "utilCf": escalated_count_cf,
        "bottomChartLabel": "昇格したエージェント数",
        "bottomRowLabelActual": "昇格数(実際)",
        "bottomRowLabelCf": "昇格数(注入した宣言が無かった場合)",
        "bottomSummaryLabelActual": "実際",
        "bottomSummaryLabelCf": "注入した宣言が無かった場合",
        "verdictText": (
            f"誰も虚偽申告していないのに権限昇格が発生する(D-60): シーン2でadminの1件の"
            f"trust宣言(単独では局所的に正当)を追加すると、既存の正直な宣言と合成され、"
            f"build_svc・ci_svcがadmin相当の権限に到達する(昇格数="
            f"{escalated_count_actual[-1]}件)。その1件を取り除けば昇格は完全に消える"
            f"(反実仮想=昇格数{escalated_count_cf[-1]}件)——単一の弱いリンク(root cause)"
            f"が全体の脆弱性を決めている、confused deputyの典型例。"
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
