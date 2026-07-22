"""④実行主体層「敵対的LLM(Red Team Agent)」をボルダ得点(順位申告)に適用する目玉シーン(D-37→D-46)。

python cases/proposal_voting/demo_llm_red_team.py で(リポジトリルートから)実行する。
事前に `pip install anthropic` と資格情報が必要(cases/credit_allocation/demo_llm_red_team.pyと同じ、
D-35で修正済みのmissing_credentials_reason()を流用)。

D-37(ケース2)は、検出ルール(信用枠)がある繰り返しゲームで敵対的LLMを試した。この
スクリプトは対照的に、検出・制裁の仕組みが存在しない1回性の投票メカニズム(ボルダ得点)
で、敵対的LLMが既知の「埋葬」戦術(BuryingStrategicAgent、真の2位を最下位に落とす)を
独立に発見するか、別の手口を選ぶかを観察する(評価観点#12、ケース2とは別角度の検証)。

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
from agents.llm_real import missing_credentials_reason
from environment import EnvironmentClient
from schemas.agent_schema import ObservationInput
from schemas.environment_schema import EnvironmentConfig
from schemas.incentive_schema import Declaration

from incentive_engine import BordaVotingEngine, BordaVotingParameters
from voting_agents import AdversarialVotingAgent, BuryingStrategicAgent, HonestVotingAgent


def main() -> int:
    reason = missing_credentials_reason()
    if reason:
        print(f"[SKIP] 敵対的LLMの目玉シーンをスキップします: {reason}")
        print("       (pip install anthropic の上、ANTHROPIC_API_KEY を設定するか `ant auth login` を実行してください)")
        return 0

    with open(_CASE_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    candidate_ids = config["mechanism"]["candidate_ids"]
    proposal_a, proposal_b, proposal_c, proposal_d = candidate_ids
    engine = BordaVotingEngine(BordaVotingParameters(candidate_ids=candidate_ids))
    env = EnvironmentClient(EnvironmentConfig(**config["environment"]))

    # generate_results_summary.pyの具体例(D-27)と同じ真の評価額を使い、既存の
    # ルールベース埋葬戦術の実績(埋葬=+50.00 / 正直=+30.00)と直接比較できるようにする。
    alice_true = {proposal_a: 10.0, proposal_b: 6.0, proposal_c: 3.0, proposal_d: 1.0}
    carol_true = {proposal_a: 9.0, proposal_b: 5.0, proposal_c: 2.0, proposal_d: 1.0}
    bob_true = {proposal_b: 10.0, proposal_a: 6.0, proposal_d: 4.0, proposal_c: 1.0}

    honest_ranking = HonestVotingAgent("bob", bob_true).true_ranking()
    known_burying_ranking = BuryingStrategicAgent("bob", bob_true).manipulated_ranking()
    print(f"(参考: bobの正直ランキング= {honest_ranking})")
    print(f"(参考: 既知のルールベース埋葬戦術のランキング= {known_burying_ranking})\n")

    print("--- Red Teamフェーズ(bobを敵対的LLMに差し替え、3ラウンド) ---\n")
    for round_index in range(1, 4):
        round_id = env.advance_round()
        alice = HonestVotingAgent("alice", alice_true)
        carol = HonestVotingAgent("carol", carol_true)
        bob = AdversarialVotingAgent("bob", bob_true, candidate_ids)

        trace_summary = {"round": round_id}
        alice_action = alice.decide(ObservationInput(trace_summary=trace_summary))
        carol_action = carol.decide(ObservationInput(trace_summary=trace_summary))
        bob_action = bob.decide(ObservationInput(trace_summary=trace_summary))

        declarations = [
            Declaration(agent_id="alice", declared_ranking=alice_action.declared_ranking),
            Declaration(agent_id="carol", declared_ranking=carol_action.declared_ranking),
            Declaration(agent_id="bob", declared_ranking=bob_action.declared_ranking),
        ]
        outcome = run_mechanism(engine, declarations)
        winner = outcome.result.allocated_agent_ids[0] if outcome.result else None

        print(f"--- ラウンド{round_index} ---")
        print(f"  bobの申告: {bob_action.declared_ranking}")
        print(f"  正直ランキングと一致?: {bob_action.declared_ranking == honest_ranking}")
        print(f"  既知の埋葬戦術と一致?: {bob_action.declared_ranking == known_burying_ranking}")
        print(f"  勝者: {winner}")
        print(f"  bobにとっての実現価値: {bob_true.get(winner, 0.0)}")
        print(f"  bobの理由づけ: {bob_action.reasoning}")
        print()

    print("敵対的LLMエージェントが、①〜③の実パイプラインに差し込めることを確認しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
