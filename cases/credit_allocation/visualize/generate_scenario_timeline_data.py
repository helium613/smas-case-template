"""cases/credit_allocation/visualize/scenario_timeline.html に埋め込む、
シーン推移データを機械的に生成するビルドスクリプト(D-41→D-57)。

python cases/credit_allocation/visualize/generate_scenario_timeline_data.py で
(リポジトリルートから)実行する。

D-41で手転記(コピペ)して埋め込んだデータに転記ミスが見つかった教訓を踏まえ、
以降はこのスクリプトで機械的に再生成する(embed_reports.py・
generate_incentive_gradient_data.pyと同じマーカー埋め込み方式)。

2つのシナリオを生成する:
- four_scene_demo: 既存の4シーンデモ(build→deviate→punish→recover、
  GreedyOverstatingAgentの逸脱、実際 vs 反実仮想honestの比較、D-24)
- punishment_loop: D-45の可視化(インセンティブ勾配)の議論から生まれた、
  「信用枠を超えて申告し続けると、初回で制裁を受け、縮小した信用枠に対しても
  同じ倍率で申告し続けるため制裁が延々とリセットされ続ける」自己永続ループ
  (倍率1.2を30ラウンド貫いた場合)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CASE_DIR = _REPO_ROOT / "cases" / "credit_allocation"
_HTML_PATH = Path(__file__).resolve().parent / "scenario_timeline.html"
_START_MARKER = "/* SCENARIOS_DATA_START (generate_scenario_timeline_data.py が機械的に更新する、手編集禁止) */"
_END_MARKER = "/* SCENARIOS_DATA_END */"

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_CASE_DIR))

from environment import EnvironmentClient
from schemas.agent_schema import ActionOutput, ObservationInput
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration

from incentive_engine import TriggerStrategyEngine, TriggerStrategyParameters, compute_credit_limit
from credit_agents import CreditAwareHonestAgent
from deviation_test import run_four_scene_demo
from payloads import CreditRoundRecord


def compute_four_scene_demo(config: dict) -> dict:
    env_config = EnvironmentConfig(**config["environment"])
    params = TriggerStrategyParameters(**config["mechanism"])
    scenario = config["scenario"]
    engine = TriggerStrategyEngine(params)
    agent_ids = ["alice", "bob", "carol"]

    def make_env() -> EnvironmentClient:
        return EnvironmentClient(env_config)

    results, comparison = run_four_scene_demo(
        agent_ids, deviating_agent_id="carol", engine=engine, env_factory=make_env,
        build_rounds=scenario["build_rounds"], deviate_rounds=scenario["deviate_rounds"],
        punishment_rounds=scenario["punishment_rounds"], recover_rounds=scenario["recover_rounds"],
        discount=scenario["discount"],
    )

    true_value_schedule = CreditAwareHonestAgent("carol", agent_ids.index("carol"), n_agents=len(agent_ids))
    post_build = [r for r in results if r.name != "scene1_build"]

    # utilActual/utilCf は「シーン2以降の累積」(D-07: 1回性とのシーン混同を避ける、
    # deviation_test.pyの既存メソッドと同じ)だが、他の配列(creditActual等)はシーン1を
    # 含む全Nラウンド分あるため、配列長をNに揃えるためシーン1(構築期)の分は0.0で
    # 埋める(build_rounds件)。これを忘れるとJSの`utilActual[N-1]`がout-of-boundsになる
    # 実装上の落とし穴(実際に踏んだ、D-57)。
    util_actual: list[float] = [0.0] * scenario["build_rounds"]
    util_cf: list[float] = [0.0] * scenario["build_rounds"]
    cumulative_actual = 0.0
    cumulative_cf = 0.0
    for t, round_result in enumerate(post_build):
        won = round_result.outcome is not None and "carol" in round_result.outcome.allocated_agent_ids
        true_value = true_value_schedule.true_value_for_round(round_result.round_id)
        cumulative_actual += (scenario["discount"] ** t) * (true_value if won else 0.0)
        util_actual.append(round(cumulative_actual, 3))
    # 反実仮想(遵守を貫いた場合)は別環境で独立実行されているため、run_four_scene_demoの
    # 内部でのみ比較済み。ここではcomparisonの最終値と整合する形で、遵守を貫いた場合の
    # honestエージェントを使い、同じ手法で改めてラウンドごとの累積を計算する。
    cf_env = make_env()
    cf_agents = [
        CreditAwareHonestAgent(a, i, n_agents=len(agent_ids)) for i, a in enumerate(agent_ids)
    ]
    from deviation_test import run_round
    cf_results = []
    for _ in range(scenario["build_rounds"]):
        run_round("scene1_build", cf_agents, engine, cf_env)
    for _ in range(scenario["deviate_rounds"] + scenario["punishment_rounds"] + scenario["recover_rounds"]):
        cf_results.append(run_round("cf", cf_agents, engine, cf_env))
    for t, round_result in enumerate(cf_results):
        won = round_result.outcome is not None and "carol" in round_result.outcome.allocated_agent_ids
        true_value = true_value_schedule.true_value_for_round(round_result.round_id)
        cumulative_cf += (scenario["discount"] ** t) * (true_value if won else 0.0)
        util_cf.append(round(cumulative_cf, 3))

    return {
        "label": "4シーンデモ(逸脱 vs 反実仮想honest)",
        "hasCounterfactual": True,
        "scenes": [
            {"name": "scene1_build", "label": "構築期",
             "rounds": [1, scenario["build_rounds"]], "color": "var(--scene-build)"},
            {"name": "scene2_deviation_injected", "label": "逸脱注入",
             "rounds": [scenario["build_rounds"] + 1, scenario["build_rounds"] + scenario["deviate_rounds"]],
             "color": "var(--scene-deviate)"},
            {"name": "scene3_trigger_active", "label": "トリガー発動",
             "rounds": [scenario["build_rounds"] + scenario["deviate_rounds"] + 1,
                        scenario["build_rounds"] + scenario["deviate_rounds"] + scenario["punishment_rounds"]],
             "color": "var(--scene-punish)"},
            {"name": "scene4_recovery", "label": "回復",
             "rounds": [scenario["build_rounds"] + scenario["deviate_rounds"] + scenario["punishment_rounds"] + 1,
                        scenario["build_rounds"] + scenario["deviate_rounds"] + scenario["punishment_rounds"] + scenario["recover_rounds"]],
             "color": "var(--scene-recover)"},
        ],
        "N": len(results),
        "sceneNames": [r.name for r in results],
        "creditActual": [round(r.credit_limits["carol"].credit_limit, 3) for r in results],
        "declaredActual": [round(next(d.declared_value for d in r.declarations if d.agent_id == "carol"), 3) for r in results],
        "compliantActual": [bool(r.compliance["carol"]) for r in results],
        "wonActual": [bool(r.outcome is not None and "carol" in r.outcome.allocated_agent_ids) for r in results],
        "utilActual": util_actual,
        "utilCf": util_cf,
        "verdictGood": not comparison.deviation_profitable,
        "verdictText": (
            f"逸脱は得にならない: 制裁で信用枠が急落し、回復にラウンドを要する間、"
            f"逸脱した場合の累積効用({comparison.actual_utility:+.2f})は反実仮想"
            f"({comparison.counterfactual_utility:+.2f})を一貫して下回り続ける(D-24)。"
        ),
    }


def compute_punishment_loop(config: dict, fraction: float = 1.2, n_rounds: int = 30) -> dict:
    env_config = EnvironmentConfig(**config["environment"])
    params = TriggerStrategyParameters(**config["mechanism"])
    engine = TriggerStrategyEngine(params)
    agent_ids = ["alice", "bob", "carol"]

    class FractionOfLimitAgent:
        def __init__(self, agent_id: str, fraction: float) -> None:
            self.agent_id = agent_id
            self.fraction = fraction

        def decide(self, observation: ObservationInput) -> ActionOutput:
            credit_limit = observation.trace_summary.get("credit_limit")
            declared_value = self.fraction * credit_limit if credit_limit is not None else 0.0
            return ActionOutput(action="bid", declared_value=declared_value, reasoning=None)

    env = EnvironmentClient(env_config)
    honest_agents = {a: CreditAwareHonestAgent(a, i, n_agents=len(agent_ids)) for i, a in enumerate(agent_ids)}
    carol = FractionOfLimitAgent("carol", fraction)
    true_value_schedule = honest_agents["carol"]

    credit_actual, declared_actual, compliant_actual, won_actual, util_actual = [], [], [], [], []
    cumulative = 0.0
    for t in range(n_rounds):
        round_id = env.advance_round()
        credit_limits = {a: compute_credit_limit(env, a, round_id, engine.parameters) for a in agent_ids}
        declarations = []
        for a in agent_ids:
            obs = ObservationInput(trace_summary={"round": round_id, "credit_limit": credit_limits[a].credit_limit})
            agent = carol if a == "carol" else honest_agents[a]
            action = agent.decide(obs)
            declarations.append(Declaration(agent_id=a, declared_value=action.declared_value))
        outcome = engine.allocate_and_pay(declarations)
        winners = set(outcome.allocated_agent_ids)
        for d in declarations:
            limit = credit_limits[d.agent_id].credit_limit
            compliant = d.declared_value <= limit + 1e-9
            env.write_trace(
                writer_id=d.agent_id,
                trace=Trace(
                    agent_id=d.agent_id, round_id=round_id,
                    payload=CreditRoundRecord(
                        declared_value=d.declared_value, credit_limit_at_declaration=limit,
                        won=d.agent_id in winners, compliant=compliant,
                    ),
                ),
            )
        carol_decl = next(d for d in declarations if d.agent_id == "carol")
        carol_limit = credit_limits["carol"].credit_limit
        carol_compliant = carol_decl.declared_value <= carol_limit + 1e-9
        carol_won = "carol" in winners
        true_value = true_value_schedule.true_value_for_round(round_id)
        cumulative += (config["scenario"]["discount"] ** t) * (true_value if carol_won else 0.0)

        credit_actual.append(round(carol_limit, 3))
        declared_actual.append(round(carol_decl.declared_value, 3))
        compliant_actual.append(bool(carol_compliant))
        won_actual.append(bool(carol_won))
        util_actual.append(round(cumulative, 3))

    return {
        "label": f"信用枠超過の自己永続ループ(倍率{fraction})",
        "hasCounterfactual": False,
        "scenes": [
            {"name": "sustained_violation", "label": f"倍率{fraction}を継続",
             "rounds": [1, n_rounds], "color": "var(--scene-punish)"},
        ],
        "N": n_rounds,
        "sceneNames": ["sustained_violation"] * n_rounds,
        "creditActual": credit_actual,
        "declaredActual": declared_actual,
        "compliantActual": compliant_actual,
        "wonActual": won_actual,
        "utilActual": util_actual,
        "utilCf": None,
        "verdictGood": None,
        "verdictText": (
            f"倍率{fraction}(信用枠の{fraction}倍)を申告し続けると、初回(ラウンド1)で"
            f"即座に違反し制裁が発動、信用枠が{config['mechanism']['punishment_limit']}まで"
            f"急落する。縮小した信用枠に対しても同じ倍率で申告し続けるため再び違反となり、"
            f"制裁が延々とリセットされ続ける自己永続ループに陥る——{n_rounds}ラウンド中、"
            f"2ラウンド目以降は一度も当選できない。累積効用は初回勝利時の真の評価額"
            f"({util_actual[-1]})で頭打ちになる。"
        ),
    }


def main() -> None:
    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    scenarios = {
        "four_scene_demo": compute_four_scene_demo(config),
        "punishment_loop": compute_punishment_loop(config),
    }

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
