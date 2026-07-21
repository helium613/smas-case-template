"""④実行主体層: 最適化ベース(scipy.optimize、CLAUDE.md 6章の実装優先度4)。

ルールベース(固定倍率で過大申告等、agents/rule_based.py)が「ハンドピックした
数点の申告値」でしか耐戦略性を検証しないのに対し、このエージェントは他エージェント
の申告額に関する確率分布(信念)を仮定し、期待効用を最大化する申告額を連続空間上で
数値的に探索する。VCGが真に耐戦略性を満たすなら、この最適化は信念分布の形状に
よらず常に真の評価額に収束するはずであり、それを実際に数値最適化で確認する、
初めての④層の手段(D-34)。

現状はdeclared_value(スカラー)のみを持つメカニズム(VCG等、mechanism_catalog.md
ファミリー1)向けの実装。ボルダ得点(順位)・Liquid Democracy(委任先)のような
組合せ的な申告空間へはそのまま拡張できず、離散最適化へ設計を変える必要がある
(プラガブル性は型の互換性のみを意味し、振る舞いの同等性は保証しない、CLAUDE.md
2章 原則4)。
"""
from __future__ import annotations

import random as random_module
from typing import Callable, Protocol

from scipy.optimize import minimize_scalar

from schemas.agent_schema import ActionOutput, ObservationInput
from schemas.incentive_schema import AllocationResult, Declaration


class ScalarBidEngine(Protocol):
    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult: ...


class OptimizingBidderAgent:
    """他エージェント(単一の競合相手を想定)の申告額の確率分布(信念)のもとで、
    期待効用(真の評価額-支払い、勝てなければ0)を最大化する申告額を
    scipy.optimize.minimize_scalarで探索する。

    competitor_bid_sampler(rng) -> float は、競合の申告額を1つサンプルする関数。
    このエージェント自身は分布の形状を知らず、サンプラーというブラックボックスと
    してのみ扱う——信念分布が変わっても最適解(=真の評価額)が変わらないことを
    確認するのがこのエージェントの存在意義(D-34)。
    """

    def __init__(
        self,
        agent_id: str,
        true_value: float,
        competitor_id: str,
        competitor_bid_sampler: Callable[[random_module.Random], float],
        engine: ScalarBidEngine,
        n_samples: int = 300,
        search_bound_multiplier: float = 3.0,
        rng: random_module.Random | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.true_value = true_value
        self.competitor_id = competitor_id
        self.competitor_bid_sampler = competitor_bid_sampler
        self.engine = engine
        self.n_samples = n_samples
        self.search_bound_multiplier = search_bound_multiplier
        self.rng = rng or random_module.Random(0)

    def _expected_utility(self, declared_value: float, competitor_bids: list[float]) -> float:
        total = 0.0
        for competitor_bid in competitor_bids:
            declarations = [
                Declaration(agent_id=self.agent_id, declared_value=declared_value),
                Declaration(agent_id=self.competitor_id, declared_value=competitor_bid),
            ]
            result = self.engine.allocate_and_pay(declarations)
            if self.agent_id in result.allocated_agent_ids:
                total += self.true_value - result.payments.get(self.agent_id, 0.0)
        return total / len(competitor_bids)

    def decide(self, observation: ObservationInput) -> ActionOutput:
        # 信念分布から固定サンプル集合を1回引き、期待効用を(サンプリング由来の
        # ノイズはあるが)決定論的な関数として最適化する。呼び出しのたびに引き直すと
        # 目的関数が揺れ動き、Brent法(bounded)が前提とする単峰性が崩れるため。
        competitor_bids = [self.competitor_bid_sampler(self.rng) for _ in range(self.n_samples)]
        result = minimize_scalar(
            lambda x: -self._expected_utility(x, competitor_bids),
            bounds=(0.0, self.true_value * self.search_bound_multiplier),
            method="bounded",
        )
        return ActionOutput(action="bid", declared_value=result.x, reasoning=None)
