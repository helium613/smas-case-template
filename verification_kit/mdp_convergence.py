"""検証キット: MDPによる収束確率評価(収束検証サブコンポーネント、pymdptoolbox利用)。

1回性エンジン(VCG等)には「遷移する状態」自体が存在しないため、この評価は
原理的に適用できない(SMAS_theorymap.md 2.1節)。1ケース目(タスク配分)の
デモでは呼び出さない。繰り返しゲーム化したケース(信用枠配分等)向けの
共通ユーティリティとして、そのまま使えるように用意しておく。
"""
from __future__ import annotations

import numpy as np
from mdptoolbox.mdp import ValueIteration


def solve_value_iteration(
    transition: np.ndarray, reward: np.ndarray, discount: float = 0.9, max_iter: int = 1000
) -> ValueIteration:
    """transition: shape (A, S, S)、reward: shape (S, A) または (A, S, S)。"""
    vi = ValueIteration(transition, reward, discount, max_iter=max_iter)
    vi.run()
    return vi


def convergence_summary(vi: ValueIteration) -> dict:
    """5大指標②収束性の1行サマリーに使う集計。"""
    return {
        "policy": vi.policy,
        "iterations": vi.iter,
        "time_seconds": vi.time,
    }
