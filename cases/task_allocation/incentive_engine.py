"""②誘因構造層(メカニズム定義層): 唯一、ケースごとに新規の数学的導出を要する層
(CLAUDE.md 2章 原則3、4章)。

    ============================================================
    このtemplateをフォークしたら、このファイルの中身を差し替える。
    ============================================================

以下は「1財・単一ラウンドのVCG(=第二価格封印入札)」の最小サンプル実装。
schemas.incentive_schema.IncentiveEngine プロトコル(version・parameters・
allocate_and_pay)を満たしてさえいれば、他の層(aggregation.py 等)からは
差し替え可能(プラガブル)であることを疎通確認するために同梱している。

耐戦略性: 正直な申告が支配戦略になる(Vickrey 1961、VCGメカニズムの特殊形)。
これは①概念層の性質を、②の中身が満たす具体例であり、他のケースでは全く
別の数式(繰り返しゲームの評判モデル等、mechanism_catalog.md参照)に置き換わる。
"""
from __future__ import annotations

from pydantic import BaseModel

from environment import EnvironmentClient
from schemas.incentive_schema import AllocationResult, Declaration, ParticipationRecord


class SingleItemVcgParameters(BaseModel):
    """このサンプルのパラメータ。ケース固有のパラメータ型に差し替える。"""

    reserve_price: float = 0.0


class SingleItemVcgEngine:
    """schemas.incentive_schema.IncentiveEngine を満たす、B側(中身)の実装例。"""

    def __init__(self, parameters: SingleItemVcgParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        if not declarations:
            return AllocationResult(allocated_agent_ids=[], payments={})

        ranked = sorted(declarations, key=lambda d: d.declared_value, reverse=True)
        winner = ranked[0]
        if winner.declared_value < self.parameters.reserve_price:
            return AllocationResult(allocated_agent_ids=[], payments={})

        second_price = ranked[1].declared_value if len(ranked) > 1 else self.parameters.reserve_price
        payment = max(second_price, self.parameters.reserve_price)
        return AllocationResult(allocated_agent_ids=[winner.agent_id], payments={winner.agent_id: payment})


# ============================================================
# 【2ケース目のプレビュー】環境の痕跡だけを根拠にした信用ゲート
# (1ケース目のデモでは使わない。DECISIONS.md D-07/D-15)
# ============================================================
#
# VCG(セカンドプライス)は数学的に耐戦略性を満たすため、過大申告そのものは
# 得にならない(シーン3の反実仮想比較・smoke_test.pyのモンテカルロで確認)。
# このゲートが対処するのは別の問題: 経済的に損なのに固定の高値を宣言し続け、
# 資源配分を独占する逸脱(公平性・#10、適応的逸脱への頑健性・#12に対応)。
#
# 【1ケース目のデモから外した理由(D-07に加えて)】このゲートをVCGに重ねると、
# 「今日の当選が明日の参加資格に影響する」ため、1回性の支配戦略分析の前提が
# 崩れる(正直申告が支配戦略であることの証明は、申告が将来の利得に影響しない
# ことを前提とする)。さらに、当選率だけでは「合理性を欠いた独占者」と
# 「正当に評価額が高い正直者」を区別できず、後者を誤って排除しうる。
# したがってこのゲートは、繰り返しゲームとして誘因設計をやり直す2ケース目で、
# ②誘因構造層の一部として(後付けのフィルタではなく)再設計する必要がある。
#
# 関数自体は、agent_id ごとの「公開されている参加記録」だけを読み、誰でも同じ
# 入力から同じ結果を再現できる決定論的な計算しかしない(この性質は2ケース目でも
# 維持する: 特定の1関数・1エージェントが「罰を下す」構造にしない)。


def compute_recent_win_rate(
    env: EnvironmentClient, agent_id: str, window_rounds: int
) -> tuple[float, int]:
    """agent_id 自身の過去の参加記録から、直近 window_rounds ラウンドでの
    当選率を計算する。読み取りは全員に公開されている(壁は書き込みのみを
    制約する)ため、この計算は誰でも同じ結果を再現できる。

    eligible=False(既に信用ゲートで除外されていた)記録は分母に含めない。
    含めてしまうと、除外されている間の「参加できなかった」事実が敗北として
    積み上がり、当選率をかえって薄めて信用を早期に回復させてしまうため。
    """
    traces = [
        t
        for t in env.read_traces(max_age_rounds=window_rounds)
        if t.agent_id == agent_id
        and isinstance(t.payload, ParticipationRecord)
        and t.payload.eligible
    ]
    if not traces:
        return 0.0, 0
    wins = sum(1 for t in traces if t.payload.won)
    return wins / len(traces), len(traces)


def filter_eligible_declarations(
    env: EnvironmentClient,
    declarations: list[Declaration],
    *,
    window_rounds: int = 5,
    min_participations: int = 3,
    max_win_rate: float = 0.7,
) -> list[Declaration]:
    """直近の当選率が異常に高い申告者を、次ラウンドの集約対象から機械的に外す。

    min_participations 未満のエージェント(参加実績が浅い新規参加者等)は対象外
    とする(判断材料が乏しい段階で誤って排除しないため)。
    """
    eligible = []
    for declaration in declarations:
        win_rate, n = compute_recent_win_rate(env, declaration.agent_id, window_rounds)
        if n >= min_participations and win_rate > max_win_rate:
            continue
        eligible.append(declaration)
    return eligible
