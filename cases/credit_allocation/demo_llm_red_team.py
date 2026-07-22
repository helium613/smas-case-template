"""④実行主体層「敵対的LLM(Red Team Agent)」の目玉シーン(CLAUDE.md 6章 優先度6)。

python cases/credit_allocation/demo_llm_red_team.py で(リポジトリルートから)実行する。
事前に `pip install anthropic` と資格情報が必要(agents/llm_real.pyと同じ、D-35で
修正済みのmissing_credentials_reason()を流用)。

D-34/D-36で、素のLLM実物(正直な参加を指示)の基準動作を確認済み。このスクリプトは
対照的に、明示的に敵対的な指示を与えたLLMが、信用枠(検出ルール)をどう扱うかを
観察する(評価観点#12、適応的逸脱への頑健性の経験的検証)。

このケース(信用枠配分)を選んだ理由: ケース1(VCG)には検出・制裁の仕組みが
そもそも存在しない(1回性・支払いによる自己拘束)。#12が問う「検出ルールを学習
して回避するような、巧妙な逸脱」が意味を持つのは、実際に違反検出と制裁がある
このケースだけである(D-37)。

CI対象外、目玉シーンのみ数回の呼び出しに限定する(execution_layer_priority.md)。
コスト抑制のため、構築期はルールベース、Red Teamフェーズのみcarolをこのエージェント
に差し替える(実API呼び出しは4回のみ)。deviation_test.run_roundを使わず、
reasoning(LLMの理由づけ)を観察できるよう、ラウンド処理をこのスクリプト内に
インラインで書く。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))
sys.path.insert(0, str(_CASE_DIR))

from aggregation import run_mechanism
from agents.llm_real import missing_credentials_reason
from agents.llm_red_team import AdversarialToolUseAgent
from environment import EnvironmentClient
from schemas.agent_schema import ObservationInput
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration

from credit_agents import CreditAwareHonestAgent
from deviation_test import run_round
from incentive_engine import TriggerStrategyEngine, TriggerStrategyParameters, compute_credit_limit
from payloads import CreditRoundRecord


def main() -> int:
    reason = missing_credentials_reason()
    if reason:
        print(f"[SKIP] 敵対的LLMの目玉シーンをスキップします: {reason}")
        print("       (pip install anthropic の上、ANTHROPIC_API_KEY を設定するか `ant auth login` を実行してください)")
        return 0

    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env = EnvironmentClient(EnvironmentConfig(**config["environment"]))
    engine = TriggerStrategyEngine(TriggerStrategyParameters(**config["mechanism"]))
    agent_ids = ["alice", "bob", "carol"]

    honest_agents = [
        CreditAwareHonestAgent(agent_id, index, n_agents=len(agent_ids))
        for index, agent_id in enumerate(agent_ids)
    ]

    print("--- 構築期(ルールベースで信用履歴を作る、5ラウンド) ---")
    for _ in range(5):
        run_round("scene1_build", honest_agents, engine, env)
    print("(完了)\n")

    print("--- Red Teamフェーズ(carolを敵対的LLMに差し替え、4ラウンド) ---\n")
    red_team_carol = AdversarialToolUseAgent("carol", true_value=15.0)
    round_agents = {
        "alice": next(a for a in honest_agents if a.agent_id == "alice"),
        "bob": next(a for a in honest_agents if a.agent_id == "bob"),
        "carol": red_team_carol,
    }

    for round_index in range(1, 5):
        round_id = env.advance_round()
        credit_limits = {
            agent_id: compute_credit_limit(env, agent_id, round_id, engine.parameters)
            for agent_id in agent_ids
        }

        declarations: list[Declaration] = []
        carol_action = None
        for agent_id in agent_ids:
            agent = round_agents[agent_id]
            trace_summary = {"round": round_id, "credit_limit": credit_limits[agent_id].credit_limit}
            action = agent.decide(ObservationInput(trace_summary=trace_summary))
            if agent_id == "carol":
                carol_action = action
            declarations.append(Declaration(agent_id=agent_id, declared_value=action.declared_value))

        outcome = run_mechanism(engine, declarations)
        winners = set(outcome.result.allocated_agent_ids) if outcome.result else set()

        for declaration in declarations:
            limit = credit_limits[declaration.agent_id].credit_limit
            compliant = declaration.declared_value <= limit + 1e-9
            record = CreditRoundRecord(
                declared_value=declaration.declared_value,
                credit_limit_at_declaration=limit,
                won=declaration.agent_id in winners,
                compliant=compliant,
            )
            env.write_trace(
                writer_id=declaration.agent_id,
                trace=Trace(agent_id=declaration.agent_id, round_id=round_id, payload=record),
            )

        carol_declaration = next(d for d in declarations if d.agent_id == "carol")
        carol_limit = credit_limits["carol"].credit_limit
        carol_compliant = carol_declaration.declared_value <= carol_limit + 1e-9
        print(f"--- ラウンド{round_index} ---")
        print(f"  carolの信用枠: {carol_limit:.2f}")
        print(f"  carolの申告: {carol_declaration.declared_value:.2f}")
        print(f"  遵守?: {carol_compliant}")
        print(f"  当選?: {'carol' in winners}")
        print(f"  carolの理由づけ: {carol_action.reasoning}")
        print()

    print("敵対的LLMエージェントが、①〜③の実パイプラインに差し込めることを確認しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
