"""②誘因構造層 A側: 型定義のみ。

配分ルール+支払いルールを不可分な1つの仕様として定義する(CLAUDE.md 4章)。
中身(B側、allocate_and_pay の実装)は engine/incentive_engine.py に書く。
②誘因構造層だけが「都度の数学的導出」を要する層である(CLAUDE.md 2章 原則3)。
"""
from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from schemas.environment_schema import InterventionRecord

P = TypeVar("P", bound=BaseModel)


class Declaration(BaseModel):
    """1エージェントからの申告。

    declared_value(単一の数値申告、支払いベースのメカニズム向け)・
    declared_ranking(順位申告、投票ベースのメカニズム向け)・delegate_to
    (委任先、委任ベースのメカニズム向け)は排他的に使う。ケース3(ボルダ得点、
    mechanism_catalog.md ファミリー2)でdeclared_rankingを、ケース4
    (Liquid Democracy、ファミリー5)でdelegate_toを追加した(CLAUDE.md 11章、
    A側変更理由の明記。ケース2はA側変更ゼロだった一方、ケース3・4は2回連続で
    追加が必要になった。5ケース目以降も同様の追加が必要になった場合は、
    汎用ペイロード(Declaration[T])への設計変更を再検討する、CLAUDE.md 11章の
    「頻度が増えたら危険信号」チェックの対象として明示的に残す)。
    """

    agent_id: str
    declared_value: float = 0.0
    declared_ranking: list[str] | None = None
    delegate_to: str | None = None


class AllocationResult(BaseModel):
    """配分+支払いの結果(不可分な1つの仕様の出力)。"""

    allocated_agent_ids: list[str]
    payments: dict[str, float]


class ParticipationRecord(BaseModel):
    """①環境層に書き込む、1ラウンド分の参加記録(申告額・当選有無・支払額)。

    declared_value・won・payment を1つにまとめて公開しておくことで、後続ラウンドは
    「公開されている事実」だけから信用シグナルを計算できる(隠れた行動の検知や
    ground truthの漏洩には依存しない、adverse selectionの範囲内で完結させる、
    CLAUDE.md 3章)。各エージェントは自分の agent_id でのみこの記録を書き込む
    (①環境層の壁、environment.EnvironmentClient.write_trace)。
    """

    declared_value: float
    won: bool
    payment: float
    eligible: bool = True
    """このラウンドで集約対象(engine.allocate_and_pay の入力)に含まれたか。

    信用ゲートで除外された場合は False。当選率の計算(compute_recent_win_rate)は
    eligible=True の記録のみを対象にする。除外されている間の「参加できなかった」
    事実を敗北として数えてしまうと、除外がかえって当選率を薄めて信用を早期に
    回復させてしまう(実際に確認済みの不具合)。除外されている間は判断材料が
    増えないため、min_participations を満たす記録が古くなって window_rounds の
    外に出るまで、機械的に排除が続く(=有限の「保護観察」期間として働く)。
    """


@runtime_checkable
class IncentiveEngine(Protocol[P]):
    """②誘因構造エンジンのA側インターフェース。

    version・parameters・配分と支払いを不可分な1つの仕様として持つ
    (smas_implementation_spec_for_cursor.md 4章)。B側(engine/incentive_engine.py)
    はこのプロトコルを満たせば、ケースごとに自由に実装してよい(構造的部分型付け)。
    """

    version: str
    parameters: P

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult: ...


class VersionedMechanism(BaseModel, Generic[P]):
    """介入ポート: パラメータのバージョン管理を行う、汎用のラッパー。

    実行中の書き換えではなく、明示的な差し替え(オフライン更新)としてのみ許可する。
    """

    version: str
    parameters: P

    def with_intervention(
        self, *, new_version: str, new_parameters: P, reason: str, applied_at_round: int
    ) -> tuple["VersionedMechanism[P]", InterventionRecord]:
        record = InterventionRecord(
            previous_version=self.version,
            new_version=new_version,
            reason=reason,
            applied_at_round=applied_at_round,
        )
        updated = VersionedMechanism(version=new_version, parameters=new_parameters)
        return updated, record
