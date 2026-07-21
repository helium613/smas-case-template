"""④実行主体層: LLMモック(確率分布モック、優先度2・モンテカルロ用に必須)。

本物のLLM呼び出しと完全に同じ入出力インターフェース(JSON Schema)を満たす。
レイテンシ・APIの挙動は再現しない(llm_mock_design_guide.md 2章)。

モックの確率分布は「仮説上の分布」であり、本物のLLMの振る舞いをどれだけ
忠実に近似しているかは検証されていない、という限界を明示しておく
(llm_mock_design_guide.md 3.3節)。
"""
from __future__ import annotations

import random

from schemas.agent_schema import ActionOutput, ObservationInput


class ProbabilisticMockAgent:
    """p_honest の確率で正直申告、それ以外は deviation_range 倍で過大申告する。"""

    def __init__(
        self,
        agent_id: str,
        true_value: float,
        p_honest: float = 0.8,
        deviation_range: tuple[float, float] = (1.1, 1.5),
        rng: random.Random | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.true_value = true_value
        self.p_honest = p_honest
        self.deviation_range = deviation_range
        self._rng = rng or random.Random()

    def decide(self, observation: ObservationInput) -> ActionOutput:
        if self._rng.random() < self.p_honest:
            return ActionOutput(action="bid", declared_value=self.true_value, reasoning=None)
        low, high = self.deviation_range
        deviated_value = self.true_value * self._rng.uniform(low, high)
        return ActionOutput(action="bid", declared_value=deviated_value, reasoning=None)
