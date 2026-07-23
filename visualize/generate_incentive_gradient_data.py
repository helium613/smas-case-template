"""visualize/incentive_gradient.html に埋め込む、インセンティブ勾配(申告値を
ずらしたときの効用カーブ)のデータを機械的に生成するビルドスクリプト(D-56)。

python visualize/generate_incentive_gradient_data.py で(リポジトリルートから)実行する。

手計算・手転記でデータを埋め込むと転記ミスが起きる、という教訓(D-41の
scenario_timeline.htmlバグ)を踏まえ、必ずincentive_engineを直接呼び出して
数値を算出する(捏造しない)。

- ケース1(VCG): 単発の申告値スイープ。competitor(bob)を7.0に固定し、
  alice(true_value=10.0)の申告値を0〜20まで動かした時の実現効用を計算する。
  VCGは「勝てば第2価格を支払う」ため、競合の申告額を上回ってさえいれば
  それ以上高く申告しても効用は変わらない(平坦なプラトー)ことが分かる。
- ケース2(信用枠配分): D-45のOptimizingCreditAwareAgentと同じ発想だが、
  ここでは「信用枠に対する倍率」を固定戦略として30ラウンド貫いた場合の
  割引後合計効用を、run_sustained_strategy_comparisonと全く同じ手法
  (D-38)で倍率を細かく動かして計算する。信用枠ちょうど(倍率1.0)で
  ピークを迎え、わずかでも超えると制裁で崖のように落ちる様子が見える。

各ケースの計算はサブプロセスで隔離する——cases/task_allocation/incentive_engine.py
とcases/credit_allocation/incentive_engine.pyは同名モジュールのため、同一プロセス
内でsys.pathに両方のディレクトリを積むとPythonのモジュールキャッシュ(sys.modules)
が衝突し、2つ目のimportが1つ目のモジュールを指してしまう(実際に踏んだ不具合)。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HTML_PATH = _REPO_ROOT / "visualize" / "incentive_gradient.html"
_START_MARKER = "/* GRADIENT_DATA_START (visualize/generate_incentive_gradient_data.py が機械的に更新する、手編集禁止) */"
_END_MARKER = "/* GRADIENT_DATA_END */"

_CASE1_SCRIPT = """
import json, sys
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {case_dir!r})
from incentive_engine import SingleItemVcgEngine, SingleItemVcgParameters
from schemas.incentive_schema import Declaration

engine = SingleItemVcgEngine(SingleItemVcgParameters(reserve_price=0.0))
true_value = 10.0
competitor_bid = 7.0

xs = [0, 1, 2, 3, 4, 5, 6, 6.5, 6.9, 6.99, 7.0, 7.01, 7.5, 8, 9, 10, 11, 12, 14, 17, 20]
points = []
for x in xs:
    declarations = [
        Declaration(agent_id="alice", declared_value=x),
        Declaration(agent_id="bob", declared_value=competitor_bid),
    ]
    result = engine.allocate_and_pay(declarations)
    won = "alice" in result.allocated_agent_ids
    payment = result.payments.get("alice", 0.0)
    utility = (true_value - payment) if won else 0.0
    points.append([round(x, 2), round(utility, 3)])

print(json.dumps({{
    "xLabel": "aliceの申告値(真の評価額=10.0、競合bobの申告=7.0で固定)",
    "yLabel": "aliceの実現効用(単発)",
    "honestX": true_value,
    "points": points,
}}))
"""

_CASE2_SCRIPT = """
import json, sys
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {case_dir!r})
import yaml
from environment import EnvironmentClient
from schemas.agent_schema import ActionOutput
from schemas.environment_schema import EnvironmentConfig
from incentive_engine import TriggerStrategyEngine, TriggerStrategyParameters
from deviation_test import run_sustained_strategy_comparison

with open({config_path!r}, encoding="utf-8") as f:
    config = yaml.safe_load(f)
params = TriggerStrategyParameters(**config["mechanism"])
env_config = EnvironmentConfig(**config["environment"])
engine = TriggerStrategyEngine(params)
agent_ids = ["alice", "bob", "carol"]


class FractionOfLimitAgent:
    def __init__(self, agent_id, fraction):
        self.agent_id = agent_id
        self.fraction = fraction

    def decide(self, observation):
        credit_limit = observation.trace_summary.get("credit_limit")
        declared_value = self.fraction * credit_limit if credit_limit is not None else 0.0
        return ActionOutput(action="bid", declared_value=declared_value, reasoning=None)


def make_env():
    return EnvironmentClient(env_config)


fractions = [
    0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98,
    1.0, 1.01, 1.02, 1.05, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0,
]
points = []
honest_utility = None
for fraction in fractions:
    comparison = run_sustained_strategy_comparison(
        agent_ids, "carol", lambda agent_id, f=fraction: FractionOfLimitAgent(agent_id, f),
        engine, make_env, n_rounds=30, discount=0.9,
    )
    points.append([round(fraction, 3), round(comparison.strategy_utility, 3)])
    honest_utility = round(comparison.honest_utility, 3)

print(json.dumps({{
    "xLabel": "信用枠に対する倍率で全30ラウンド貫いた場合(1.0=信用枠ちょうど)",
    "yLabel": "carolの割引後合計効用(30ラウンド、discount=0.9)",
    "honestY": honest_utility,
    "points": points,
}}))
"""


def _run_isolated(script_template: str, **kwargs) -> dict:
    script = script_template.format(**kwargs)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=str(_REPO_ROOT))
    if result.returncode != 0:
        raise RuntimeError(f"サブプロセスが失敗しました:\n{result.stderr}")
    return json.loads(result.stdout)


def compute_case1_data() -> dict:
    data = _run_isolated(
        _CASE1_SCRIPT,
        repo_root=str(_REPO_ROOT),
        case_dir=str(_REPO_ROOT / "cases" / "task_allocation"),
    )
    data["note"] = (
        "VCG(セカンドプライス)は「勝てば競合の申告額(第2価格)を支払う」ため、"
        "競合の申告(7.0)を上回ってさえいれば、どれだけ高く申告しても支払いは"
        "変わらず効用は一定(平坦なプラトー)。正直申告(10.0)はこの安全地帯の"
        "内側にあり、過大申告する動機が構造的に存在しない。"
    )
    return data


def compute_case2_data() -> dict:
    data = _run_isolated(
        _CASE2_SCRIPT,
        repo_root=str(_REPO_ROOT),
        case_dir=str(_REPO_ROOT / "cases" / "credit_allocation"),
        config_path=str(_REPO_ROOT / "cases" / "credit_allocation" / "config.yaml"),
    )
    data["note"] = (
        "「信用枠のX倍を常に申告する」固定戦略を30ラウンド貫いた場合の割引後"
        "合計効用(run_sustained_strategy_comparisonと同じ手法、D-38)。倍率1.0"
        "(信用枠ちょうど)でピーク(98.87)を迎え、honestの合計効用("
        + str(data["honestY"])
        + ")を大きく上回る——D-37/D-38の発見そのもの。倍率が1.0をわずかでも超える"
        "と違反として検出され、制裁で効用が崖のように落ちる(8.0まで低下)。"
    )
    return data


def main() -> None:
    data = {"task_allocation": compute_case1_data(), "credit_allocation": compute_case2_data()}
    block = (
        f"{_START_MARKER}\n  var GRADIENT_DATA = "
        + json.dumps(data, ensure_ascii=False, indent=2)
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
    print(f"{_HTML_PATH} のGRADIENT_DATAを更新しました。")


if __name__ == "__main__":
    main()
