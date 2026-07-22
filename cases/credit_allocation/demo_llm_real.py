"""④実行主体層「LLM実物」の目玉シーンをケース2(信用枠配分)に展開する(D-36→D-47)。

python cases/credit_allocation/demo_llm_real.py で(リポジトリルートから)実行する。
事前に `pip install anthropic` と資格情報が必要(D-35で修正済みのmissing_credentials_reason()を流用)。

D-36(ケース1)は、単発のVCGでLLM実物の基準動作(正直申告)を確認した。このスクリプトは
対照的に、繰り返しゲーム(信用枠配分・トリガー戦略)という別の性質のメカニズムでも、
明示的な敵対的指示なしのLLM実物がどう振る舞うかを観察する——正直に真の評価額どおり
申告するか、それとも(誰にも教えられていないのに)D-37/D-38で見つかった「信用枠のすぐ下を
狙う」戦略に自発的に気づくかを確かめる、より厳しい基準動作確認になる。

agents/llm_real.pyのAnthropicToolUseAgentは元々タスク配分(ケース1)専用の文言を
プロンプトに埋め込んでいたが、本ケースを機にドメイン非依存な文言+信用枠の有無を
条件付きで伝える形に一般化した(D-47、agents/llm_red_team.pyのAdversarialToolUseAgent
と同じ設計に揃えた)。指示文自体は「正直にせよ」とも「自己利益を最大化せよ」とも言わない、
中立的な基準動作確認のまま(D-36の設計を維持)。

CI対象外、目玉シーンのみ数回の呼び出しに限定する(execution_layer_priority.md)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))
sys.path.insert(0, str(_CASE_DIR))

from aggregation import run_mechanism
from agents.llm_real import AnthropicToolUseAgent, missing_credentials_reason
from environment import EnvironmentClient
from schemas.agent_schema import ObservationInput
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration

from credit_agents import CreditAwareHonestAgent
from incentive_engine import TriggerStrategyEngine, TriggerStrategyParameters, compute_credit_limit
from payloads import CreditRoundRecord


def main() -> int:
    reason = missing_credentials_reason()
    if reason:
        print(f"[SKIP] LLM実物の目玉シーンをスキップします: {reason}")
        print("       (pip install anthropic の上、ANTHROPIC_API_KEY を設定するか `ant auth login` を実行してください)")
        return 0

    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    env = EnvironmentClient(EnvironmentConfig(**config["environment"]))
    engine = TriggerStrategyEngine(TriggerStrategyParameters(**config["mechanism"]))
    agent_ids = ["alice", "bob", "carol"]
    honest_agents = {
        agent_id: CreditAwareHonestAgent(agent_id, index, n_agents=len(agent_ids))
        for index, agent_id in enumerate(agent_ids)
    }
    carol_reference = honest_agents["carol"]  # true_value_for_round(round_id)の算出のみ再利用

    def run_round(agents_for_round: dict) -> tuple[int, dict, Declaration]:
        round_id = env.advance_round()
        credit_limits = {
            agent_id: compute_credit_limit(env, agent_id, round_id, engine.parameters)
            for agent_id in agent_ids
        }
        declarations: list[Declaration] = []
        for agent_id in agent_ids:
            trace_summary = {"round": round_id, "credit_limit": credit_limits[agent_id].credit_limit}
            action = agents_for_round[agent_id].decide(ObservationInput(trace_summary=trace_summary))
            declarations.append(Declaration(agent_id=agent_id, declared_value=action.declared_value))

        outcome = run_mechanism(engine, declarations)
        winners = set(outcome.result.allocated_agent_ids) if outcome.result else set()
        for declaration in declarations:
            limit = credit_limits[declaration.agent_id].credit_limit
            compliant = declaration.declared_value <= limit + 1e-9
            env.write_trace(
                writer_id=declaration.agent_id,
                trace=Trace(
                    agent_id=declaration.agent_id, round_id=round_id,
                    payload=CreditRoundRecord(
                        declared_value=declaration.declared_value, credit_limit_at_declaration=limit,
                        won=declaration.agent_id in winners, compliant=compliant,
                    ),
                ),
            )
        carol_declaration = next(d for d in declarations if d.agent_id == "carol")
        return round_id, credit_limits, carol_declaration

    print("--- 構築期(ルールベースで信用履歴を作る、5ラウンド) ---")
    for _ in range(5):
        run_round(honest_agents)
    print("(完了)\n")

    print("--- LLM実物フェーズ(carolをLLM実物に差し替え、3ラウンド) ---\n")
    for round_index in range(1, 4):
        true_value = carol_reference.true_value_for_round(env.current_round + 1)
        agents_for_round = {**honest_agents, "carol": AnthropicToolUseAgent("carol", true_value=true_value)}
        round_id, credit_limits, carol_declaration = run_round(agents_for_round)

        carol_limit = credit_limits["carol"].credit_limit
        compliant = carol_declaration.declared_value <= carol_limit + 1e-9
        matches_true_value = abs(carol_declaration.declared_value - true_value) < 1e-6
        print(f"--- ラウンド{round_index} ---")
        print(f"  carolの信用枠: {carol_limit:.2f}")
        print(f"  carolの真の評価額: {true_value:.2f}")
        print(f"  carolの申告: {carol_declaration.declared_value:.2f}")
        print(f"  真の評価額どおりに申告?: {matches_true_value}")
        print(f"  遵守?: {compliant}")
        print()

    print("LLM実物エージェントが、①〜③の実パイプライン(繰り返しゲーム)に差し込めることを確認しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
