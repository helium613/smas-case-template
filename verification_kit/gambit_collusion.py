"""検証キット: pygambitによる結託耐性の検証(評価観点#5)。

D-25で発見されたギャップ(pygambitは技術スタックに③頑健性用として当初から
記載されていたが、4ケースを通じて一度もコードで使われていなかった)を埋める。

単独逸脱の非収益性(モンテカルロ・MDP)とは異なる軸を検証する: 複数エージェントが
結託(coordinated deviation)した場合、誘因構造を出し抜けないか。2エージェントの
離散化した戦略空間から戦略形ゲームを構築し、pygambitで純戦略ナッシュ均衡を
すべて列挙する。単独逸脱に対して耐戦略性を満たすメカニズムでも、「非ピボットな
(勝敗を左右しない)プレイヤーが複数の戦略に対して無差別」であるために複数の
均衡が併存しうる——結託側が外部のサイドペイメントでその中から自分たちに有利な
均衡を選べてしまう、というのが結託の実体(VCG等の既知の脆弱性、D-33)。

この検証で確認できるのは「合計効用がより高い均衡が存在するか」までであり、
サイドペイメントの執行自体はスコープ外(scope_exclusions_and_deferrals.md
Part 0「支払いの執行と沈め先」と同じ、外生的に保証されると仮定する前提)。

戦略の型は数値(VCGの申告額、D-33)に限らない——ケース3(ボルダ得点、D-39)では
順位申告(list[str])を戦略として扱う。`==`比較のみに依存するため、任意の
hashable/比較可能な型に対して汎用的に使える(TypeVarで型付け)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TypeVar

import pygambit

T = TypeVar("T")


@dataclass
class CollusionCheckResult:
    equilibria_found: int
    equilibria_profiles: list[tuple[object, object]]
    honest_combined_utility: float
    best_colluding_combined_utility: float
    best_colluding_profile: tuple[object, object]

    @property
    def collusion_profitable(self) -> bool:
        """結託側の合計効用が、正直な戦略プロファイルより高い均衡が存在するか。

        Trueは「耐戦略性を満たさない(結託の余地がある)」ことを意味する
        (ケース3のmanipulation_profitableと同じ極性: Trueが問題ありのサイン)。
        """
        return self.best_colluding_combined_utility > self.honest_combined_utility + 1e-9


def check_pure_nash_collusion(
    strategies_a: list[T],
    strategies_b: list[T],
    payoff_fn: Callable[[T, T], tuple[float, float]],
    honest_strategy_a: T,
    honest_strategy_b: T,
) -> CollusionCheckResult:
    """2エージェントの離散化した戦略空間から戦略形ゲームを構築し、pygambitで
    純戦略ナッシュ均衡をすべて列挙する。

    payoff_fn(strategy_a, strategy_b) -> (utility_a, utility_b) は呼び出し側が
    ②誘因構造エンジンを使って計算する(結託しない他のエージェントは呼び出し側が
    固定した上でクロージャに含める、一撃逸脱原理と同じ「他を固定する」設計、D-25)。
    """
    game = pygambit.Game.new_table([len(strategies_a), len(strategies_b)])
    players = list(game.players)
    strat_a = list(players[0].strategies)
    strat_b = list(players[1].strategies)

    payoffs: dict[tuple[int, int], tuple[float, float]] = {}
    for i, a in enumerate(strategies_a):
        for j, b in enumerate(strategies_b):
            ua, ub = payoff_fn(a, b)
            profile = game[strat_a[i], strat_b[j]]
            profile[players[0]] = pygambit.Decimal(ua)
            profile[players[1]] = pygambit.Decimal(ub)
            payoffs[(i, j)] = (ua, ub)

    result = pygambit.nash.enumpure_solve(game)

    honest_i = strategies_a.index(honest_strategy_a)
    honest_j = strategies_b.index(honest_strategy_b)
    honest_combined = sum(payoffs[(honest_i, honest_j)])

    best_combined = honest_combined
    best_profile = (honest_strategy_a, honest_strategy_b)
    equilibria_profiles: list[tuple[float, float]] = []

    for eq in result.equilibria:
        i = next(idx for idx, (_, prob) in enumerate(eq[players[0]]) if prob == 1)
        j = next(idx for idx, (_, prob) in enumerate(eq[players[1]]) if prob == 1)
        equilibria_profiles.append((strategies_a[i], strategies_b[j]))
        combined = sum(payoffs[(i, j)])
        if combined > best_combined:
            best_combined = combined
            best_profile = (strategies_a[i], strategies_b[j])

    return CollusionCheckResult(
        equilibria_found=len(result.equilibria),
        equilibria_profiles=equilibria_profiles,
        honest_combined_utility=honest_combined,
        best_colluding_combined_utility=best_combined,
        best_colluding_profile=best_profile,
    )
