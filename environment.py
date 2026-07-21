"""①環境層: ストレージ層(痕跡の読み書き・減衰)+ 横断的アクセス制御(壁)の共通実装。

CLAUDE.md 2章 原則1: この層が唯一の「データの実体」を持つ場所。
LangGraph等フレームワークのStateには、EnvironmentClientへの参照だけを持たせ、
データそのものを複製・保持してはならない(参照プロキシパターン、CLAUDE.md 7章)。

このファイルは「そのまま使う」共通実装(CLAUDE.md 4章の責務分離表)。
ケースごとに変えるのは payload の型(schemas側で定義)と config.yaml の値のみ。
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from schemas.environment_schema import EnvironmentConfig, InterventionRecord, Trace

T = TypeVar("T", bound=BaseModel)


class WallViolation(PermissionError):
    """壁(アクセス制御)への違反: 自分の agent_id 以外の領域への書き込み試行。

    誰にも「他の主体の代わりに書き込む」権限を与えない。これが「隠れた中央集権」
    を防ぐ、①環境層側の担保(architecture_overview.md「集権化させないための原則」)。
    """


class EnvironmentClient(Generic[T]):
    """①環境層への唯一の窓口。"""

    def __init__(self, config: EnvironmentConfig) -> None:
        self._config = config
        self._traces: list[Trace[T]] = []
        self._interventions: list[InterventionRecord] = []
        self._current_round = 0

    @property
    def current_round(self) -> int:
        return self._current_round

    def advance_round(self) -> int:
        """ラウンドを1つ進める。①環境層のみがラウンド管理の実体を持つ。"""
        self._current_round += 1
        return self._current_round

    def write_trace(self, writer_id: str, trace: Trace[T]) -> None:
        """壁: writer_id は trace.agent_id と一致しなければならない(自領域のみ書き込み可)。

        書き込みは自領域のみ、という制約そのものが「壁」の実体であり、
        誰か1人(1関数)が全員の痕跡を代理で書き換えられる経路を作らない。
        """
        if writer_id != trace.agent_id:
            raise WallViolation(
                f"{writer_id} は agent_id={trace.agent_id} の領域に書き込む権限がありません"
            )
        self._traces.append(trace)

    def read_traces(self, *, max_age_rounds: int | None = None) -> list[Trace[T]]:
        """参加=読み取り行為に統一する。読み取りは全員に公開(壁は書き込みのみを制約する)。"""
        max_age = self._config.max_trace_age_rounds if max_age_rounds is None else max_age_rounds
        cutoff = self._current_round - max_age
        return [t for t in self._traces if t.round_id >= cutoff]

    def trace_weight(self, trace: Trace[T]) -> float:
        """減衰関数(evaporation): 指数減衰。half_life_rounds で重みが半分になる。

        線形減衰ではなく指数減衰を既定にする理由: どちらの形が系の挙動(記憶の長さ)
        に適するかはケース依存のため(refinement_priorities.md ①環境層)、
        まずは制御しやすいパラメータ(半減期)を持つ指数減衰を既定として用意する。
        """
        age = self._current_round - trace.round_id
        if age <= 0:
            return 1.0
        return 0.5 ** (age / self._config.half_life_rounds)

    def record_intervention(self, record: InterventionRecord) -> None:
        """介入ポート: ルール・メカニズムのバージョン更新を監査可能な形で記録する。"""
        self._interventions.append(record)

    @property
    def intervention_history(self) -> list[InterventionRecord]:
        return list(self._interventions)
