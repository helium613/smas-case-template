"""②収束性(MDP): 信用枠配分が「常に遵守」を最適方策として収束させるかを検証する。

1回性エンジン(ケース1・VCG)には適用対象外だったMDPが、繰り返しゲームである
このケースで初めて本来の役割(SMAS_theorymap.md 2.1節、verification_kit/
mdp_convergence.py)を果たす。フォーク定理の不等式(誘惑の一時的な利得 <
制裁による将来効用の割引現在価値の損失)を、状態遷移として明示的にモデル化し、
value iterationで「常に遵守」が最適方策になるかを機械的に確認する。

状態: 0=通常(遵守中)、1..punishment_rounds=制裁中(残りラウンド数)
行動: 0=遵守、1=違反(信用枠を無視して申告)
遷移: 通常×遵守→通常。通常×違反→制裁(残りpunishment_rounds)。
      制裁k×(行動によらず)→制裁k-1(k>1) または 通常(k=1)。
報酬: 通常×遵守=honest_reward(競合下での期待効用)。通常×違反=temptation_reward
      (信用枠を無視した一時的な勝利による期待効用)。制裁中は行動によらず0
      (deviation_test.pyのシーン3が示す通り、制裁中はほぼ勝てないため)。

このモデルは cases/credit_allocation/deviation_test.py の実際の4シーンデモを
単純化した抽象化であり、実装そのものの再現ではない(⑤検証層の位置づけと同じ、
「境界の型」ではなく「性質」を確認する道具)。honest_reward・temptation_rewardの
具体値は、config.yamlのmechanism/scenarioパラメータと整合する概算値を用いる。
"""
from __future__ import annotations

import numpy as np

from verification_kit.mdp_convergence import convergence_summary, solve_value_iteration


def build_mdp(
    punishment_rounds: int,
    honest_reward: float,
    temptation_reward: float,
    punishment_reward: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """状態0=通常、状態1..punishment_rounds=制裁(残りラウンド数)のMDPを構築する。

    戻り値: (transition[A,S,S], reward[S,A])。A=2(遵守/違反)、S=punishment_rounds+1。
    """
    n_states = punishment_rounds + 1
    n_actions = 2  # 0=遵守, 1=違反
    transition = np.zeros((n_actions, n_states, n_states))
    reward = np.zeros((n_states, n_actions))

    # 状態0(通常)
    transition[0, 0, 0] = 1.0  # 遵守→通常のまま
    reward[0, 0] = honest_reward
    if punishment_rounds > 0:
        transition[1, 0, punishment_rounds] = 1.0  # 違反→制裁(満期)開始
    else:
        transition[1, 0, 0] = 1.0  # 制裁期間0なら実質抑止力なし(パラメータ検証用の縮退ケース)
    reward[0, 1] = temptation_reward

    # 状態k(制裁、残りk)。行動によらず同じ遷移・報酬(申告内容に依存しない固定挙動、
    # CLAUDE.md 8章の打ち切りルールと同じ原則)。
    for k in range(1, n_states):
        next_state = k - 1
        transition[0, k, next_state] = 1.0
        transition[1, k, next_state] = 1.0
        reward[k, 0] = punishment_reward
        reward[k, 1] = punishment_reward

    return transition, reward


def check_honesty_converges(
    *,
    punishment_rounds: int,
    honest_reward: float,
    temptation_reward: float,
    discount: float,
    punishment_reward: float = 0.0,
) -> dict:
    """状態0(通常)での最適方策が「遵守」(action=0)になるかを確認する。

    5大指標②収束性の根拠として使う: 「常に遵守」が繰り返しゲームの均衡(最適方策)
    として収束するなら、耐戦略性が単発の反実仮想比較だけでなく、無限繰り返しの
    枠組みでも理論的に裏付けられる(evaluation_criteria.md #7 時間発展・繰り返し
    ゲームでの安定性)。
    """
    transition, reward = build_mdp(punishment_rounds, honest_reward, temptation_reward, punishment_reward)
    vi = solve_value_iteration(transition, reward, discount=discount)
    summary = convergence_summary(vi)
    optimal_action_at_normal = int(vi.policy[0])
    honesty_is_optimal = optimal_action_at_normal == 0
    return {
        "honesty_is_optimal": honesty_is_optimal,
        "optimal_action_at_normal_state": "honest" if honesty_is_optimal else "violate",
        "value_at_normal_state": float(vi.V[0]),
        "iterations": summary["iterations"],
        "time_seconds": summary["time_seconds"],
    }
