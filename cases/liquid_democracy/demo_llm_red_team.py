"""④実行主体層「敵対的LLM(Red Team Agent)」をLiquid Democracy(投票・委任)に
適用する目玉シーン(D-37/D-46→D-55)。

python cases/liquid_democracy/demo_llm_red_team.py で(リポジトリルートから)実行する。
事前に `pip install anthropic` と資格情報が必要(cases/credit_allocation/demo_llm_red_team.py
と同じ、D-35で修正済みのmissing_credentials_reason()を流用)。

D-48はpygambitで「委任構造を組み合わせても、正直な投票を上回る結託の均衡は存在
しない」と数式で証明した。このスクリプトは、その証明を敵対的LLMに一切教えずに
「手段を問わず自己利益を最大化せよ」と指示し、実際に何を試みるかを観察する——
理論的証明を実証で反証しにいく試み(D-46/D-47と同じ観察スタンス)。

シナリオはD-48のpygambit検証と似た、ぎりぎりの構成: alice/carol="no"固定、
frank="yes"固定、bob=敵対的LLM(真の選好="yes")。bobが素直に投票すれば
yes=2/no=2の同点(choices=["yes","no"]の並び順でyesが勝つ)——honestが
既に最善の結果を達成できる場面で、LLMがそれでも「もっと良い手」を探して
崩れないかを試す(ケース3のD-46で見られた「創意工夫が裏目に出る」現象の再検証)。

CI対象外、目玉シーンのみ数回の呼び出しに限定する(execution_layer_priority.md)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CASE_DIR.parents[1]))
sys.path.insert(0, str(_CASE_DIR))

from agents.llm_real import missing_credentials_reason
from environment import EnvironmentClient
from schemas.agent_schema import ObservationInput
from schemas.environment_schema import EnvironmentConfig, Trace
from schemas.incentive_schema import Declaration

from delegation_agents import AdversarialDelegationAgent, DirectVotingAgent
from incentive_engine import LiquidDemocracyEngine, LiquidDemocracyParameters


def main() -> int:
    reason = missing_credentials_reason()
    if reason:
        print(f"[SKIP] 敵対的LLMの目玉シーンをスキップします: {reason}")
        print("       (pip install anthropic の上、ANTHROPIC_API_KEY を設定するか `ant auth login` を実行してください)")
        return 0

    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    params = LiquidDemocracyParameters(**config["mechanism"])
    engine = LiquidDemocracyEngine(params)
    env = EnvironmentClient(EnvironmentConfig(**config["environment"]))

    agent_ids = ["alice", "carol", "frank", "bob"]
    print(f"(参考: 固定エージェント alice=no, carol=no, frank=yes。bobの真の選好=yes)")
    print("(参考: bobが素直に投票すればyes=2/no=2の同点となり、並び順によりyesが勝つ——honestが既に最善)\n")

    print("--- Red Teamフェーズ(bobを敵対的LLMに差し替え、3ラウンド) ---\n")
    for round_index in range(1, 4):
        round_id = env.advance_round()
        alice = DirectVotingAgent("alice", "no")
        carol = DirectVotingAgent("carol", "no")
        frank = DirectVotingAgent("frank", "yes")
        bob = AdversarialDelegationAgent("bob", "yes", params.choices, other_agent_ids=["alice", "carol", "frank"])

        trace_summary = {"round": round_id}
        actions = {
            "alice": alice.decide(ObservationInput(trace_summary=trace_summary)),
            "carol": carol.decide(ObservationInput(trace_summary=trace_summary)),
            "frank": frank.decide(ObservationInput(trace_summary=trace_summary)),
            "bob": bob.decide(ObservationInput(trace_summary=trace_summary)),
        }
        declarations = [
            Declaration(
                agent_id=agent_id,
                declared_ranking=action.declared_ranking,
                delegate_to=action.delegate_to,
            )
            for agent_id, action in actions.items()
        ]

        resolved = engine.resolve_delegations(declarations)
        outcome = engine.allocate_and_pay(declarations)
        winner = outcome.allocated_agent_ids[0] if outcome.allocated_agent_ids else None

        for declaration in declarations:
            env.write_trace(
                writer_id=declaration.agent_id,
                trace=Trace(
                    agent_id=declaration.agent_id, round_id=round_id, payload=declaration,
                    process_trace={"resolved_choice": resolved.get(declaration.agent_id)},
                ),
            )

        bob_action = actions["bob"]
        print(f"--- ラウンド{round_index} ---")
        print(f"  bobの行動: action={bob_action.action}, "
              f"choice={bob_action.declared_ranking}, delegate_to={bob_action.delegate_to}")
        print(f"  bobの実効票の解決先: {resolved.get('bob')}")
        print(f"  勝者: {winner}")
        print(f"  bobにとっての結果: {'望みどおり(yes勝利)' if winner == 'yes' else '不本意(no勝利)'}")
        print(f"  bobの理由づけ: {bob_action.reasoning}")
        print()

    print("敵対的LLMエージェントが、①〜③の実パイプライン(委任)に差し込めることを確認しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
