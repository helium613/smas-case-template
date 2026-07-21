"""①環境層 A側: 型定義のみ。ロジックは持たない(実装は environment.py)。

CLAUDE.md 2章 原則2(A/B構造)・原則1(中央の執行者を作らない)に対応する。
痕跡の中身(Trace.payload)は「何でも入るdict」にせず、②誘因構造層と同じ
ジェネリック型(A/B構造)にする(smas_implementation_spec_for_cursor.md 2.2節)。
"""
from __future__ import annotations

import time
import uuid
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class Trace(BaseModel, Generic[T]):
    """①環境層に書き込まれる、唯一のデータ単位。

    payload の型はケースごとに定義する(例: Declaration、CreditPayload等)。
    process_trace は隠れた行動(モラルハザード)対応向けの任意拡張ポイント。
    中身の設計はスコープ外(scope_exclusions_and_deferrals.md Part1参照)。
    """

    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: str
    round_id: int
    created_at: float = Field(default_factory=time.time)
    payload: T
    process_trace: Optional[dict] = None


class EnvironmentConfig(BaseModel):
    """①環境層のパラメータ。構造は共通、値はケース依存(config.yamlから読み込む)。"""

    half_life_rounds: float = Field(gt=0)
    max_trace_age_rounds: int = Field(gt=0)


class InterventionRecord(BaseModel):
    """介入ポート: ルール・メカニズムのバージョン更新を記録する監査ログ。

    実行中のこっそりした書き換えではなく、オフラインでの明示的な差し替えとして
    のみ許可する(不完備契約理論の裏付け、smas_project_spec.md 1章)。
    """

    previous_version: str
    new_version: str
    reason: str
    applied_at_round: int
