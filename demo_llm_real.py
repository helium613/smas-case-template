"""④実行主体層「LLM実物」の目玉シーン(execution_layer_priority.md 優先度3)。

python demo_llm_real.py で実行する。事前に `pip install anthropic` と、
`ANTHROPIC_API_KEY`(または`ant auth login`)による認証が必要。

smoke_test.py(CI対象)とは意図的に分離している: LLM実物は「目玉シーンのみ
数回」の呼び出しに限定する方針(agent_layer_variations.md モック/実物の
使い分けマトリクス)であり、大量試行・CIでの毎回実行には使わない。資格情報が
無い環境では例外で落とさず、その旨を表示してスキップする。

honest_agents(ルールベース)2体 + AnthropicToolUseAgent(LLM実物)1体を、
scenarios.deviation_test.run_scene に通して実行する。スタンドアロンのAPI
呼び出しではなく、①環境層・②誘因構造層(VCG)を含む実際のパイプラインに
LLM実物を差し込めることを示す(④実行主体層のプラガブル性、CLAUDE.md 2章
原則4: 型の互換性は保証するが、振る舞いの同等性は保証しない)。
"""
from __future__ import annotations

import sys

import yaml

from agents.llm_real import AnthropicToolUseAgent, missing_credentials_reason
from agents.rule_based import HonestRuleBasedAgent
from engine.incentive_engine import SingleItemVcgEngine, SingleItemVcgParameters
from environment import EnvironmentClient
from schemas.environment_schema import EnvironmentConfig
from scenarios.deviation_test import run_scene


def main() -> int:
    reason = missing_credentials_reason()
    if reason:
        print(f"[SKIP] LLM実物の目玉シーンをスキップします: {reason}")
        print("       (pip install anthropic の上、ANTHROPIC_API_KEY を設定するか `ant auth login` を実行してください)")
        return 0

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env = EnvironmentClient(EnvironmentConfig(**config["environment"]))
    engine = SingleItemVcgEngine(SingleItemVcgParameters(reserve_price=0.0))

    agents = [
        HonestRuleBasedAgent("alice", true_value=10.0),
        HonestRuleBasedAgent("bob", true_value=7.0),
        AnthropicToolUseAgent("carol", true_value=9.0),
    ]

    print("LLM実物(claude-opus-4-8)を含む3エージェントで、シーン1相当を2ラウンド実行します。\n")
    for round_index in range(1, 3):
        print(f"--- ラウンド{round_index} ---")
        result = run_scene(f"llm_real_demo_round{round_index}", agents, engine, env)
        for declaration in result.declarations:
            won = result.outcome.result is not None and declaration.agent_id in result.outcome.result.allocated_agent_ids
            print(f"  {declaration.agent_id}: 申告={declaration.declared_value:.2f} 当選={'Yes' if won else 'No'}")
        carol_action = next(a for a in agents if a.agent_id == "carol")
        print(f"  (carolは真の評価額={carol_action.true_value}をLLM実物経由で申告)")

    print("\nLLM実物エージェントが、①〜③の実パイプラインに差し込めることを確認しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
