"""ケース2固有の①環境層ペイロード型(Trace[T]のT、A/B構造)。

smas_implementation_spec_for_cursor.md 2.2節が示す「Trace[T]のTをケースごとに
定義する(例: TaskAllocationPayload, CreditPayload等)」という方針どおり、
共通のschemas/には置かず、ケース固有ファイルとして定義する。
"""
from __future__ import annotations

from pydantic import BaseModel


class CreditRoundRecord(BaseModel):
    """①環境層に書き込む、1ラウンド分の記録(申告額・当選有無・当時の信用枠・遵守有無)。

    支払いは発生しない(ケース1のParticipationRecord.paymentに相当する概念がない)
    メカニズムのため、ParticipationRecordを流用せず新規に定義する(D-15の反省を踏まえ、
    「別ドメインの型を無理に使い回さない」)。

    credit_limit_at_declaration を記録に含めるのは、信用枠自体が時間とともに変わる
    ため、「そのラウンド時点で何が遵守だったか」を後から機械的に再現できるようにする
    ためである(ケース1のParticipationRecord.eligibleと同じ思想)。
    """

    declared_value: float
    credit_limit_at_declaration: float
    won: bool
    compliant: bool
    """declared_value <= credit_limit_at_declaration だったか。観測可能な事実のみで
    判定し、真の評価額(観測不可能)には一切依存しない(scope_exclusions_and_deferrals.md
    Part 0、モラルハザード除外の原則をケース2でも維持)。"""
