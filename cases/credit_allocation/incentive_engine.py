"""②誘因構造層(メカニズム定義層): 信用枠配分(繰り返しゲーム、限定的懲罰トリガー戦略)。

cases/task_allocation/incentive_engine.py(VCG、支払いあり、1回性)とは対照的に、
支払いを一切伴わない配分ルールとして設計する(mechanism_catalog.md ファミリー4)。

配分ルールそのもの(allocate_and_pay)は「申告値が最も高い者が勝つ、支払いなし」という
単純な規則で、単一ラウンドだけ見れば正直申告(=信用枠以内での申告)は支配戦略ではない
——信用枠を無視して過大申告する方が、単一ラウンドでは常に得になる。それでも正直申告が
均衡になるのは、繰り返しによる将来の信用喪失という脅し(フォーク定理)による、というのが
このケースの理論的な核心。この設計により、ケース1(VCG、支払いによる1ラウンド完結の
耐戦略性)とケース2(トリガー戦略、繰り返しによる耐戦略性)という、性質の異なる2つの
メカニズムファミリーを実証する(mechanism_catalog.md Part1の「複数ファミリーの実装で
"型として受け入れられる"ことを示す」という方針)。

信用枠(credit_limit)は申告や配分結果とは別に、公開痕跡(CreditRoundRecord)から
毎回決定論的に導出する(誰でも同じ入力から同じ結果を再現できる、ケース1のcompute_
recent_win_rateと同じ思想)。導出規則:

- 違反(declared_value > credit_limit_at_declaration)が一度でも記録されたら、その
  ラウンドから punishment_rounds の間、信用枠を punishment_limit まで固定的に縮小する
  (制裁中の信用枠は、その間の申告内容に一切依存しない——ケース1の打ち切りルールと同じ
  「フォールバックは申告内容に依存しない固定の挙動にする」原則)
- 制裁期間外(直近の違反から punishment_rounds を超えて経過、または違反履歴なし)は、
  base_limit を起点に、直近の遵守記録を①環境層の既存の減衰関数(EnvironmentClient.
  trace_weight、指数減衰)で時系列に重み付けした合計だけ信用枠が緩やかに拡大する
  (architecture_overview.md「集約の中身: 時系列の重み付き平均」に対応。減衰関数自体は
  ①環境層の共通実装をそのまま使い、集約規則(重み付き合計→信用枠への変換)だけを
  ここで新規に定義する)
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from environment import EnvironmentClient
from schemas.incentive_schema import AllocationResult, Declaration

from payloads import CreditRoundRecord


class TriggerStrategyParameters(BaseModel):
    """信用枠配分メカニズムのパラメータ(介入ポートで更新しうる値、D-22)。"""

    base_limit: float = 10.0
    """遵守を続けている(制裁期間外)エージェントの、信用枠の起点値。"""

    max_limit: float = 30.0
    """信用枠の上限。"""

    growth_rate: float = 4.0
    """時系列の重み付き遵守合計 1 あたり、信用枠がどれだけ拡大するか。"""

    punishment_rounds: int = 5
    """違反1回あたりの制裁期間(ラウンド数)。無期限のgrim triggerではなく、期限付き
    制裁にすることで、"寛容さの設計"の課題に応える(mechanism_catalog.md ファミリー4)。"""

    punishment_limit: float = 0.5
    """制裁中の信用枠。完全にゼロにはせず、最低限の参加(判断材料の蓄積)は許す。"""


class TriggerStrategyEngine:
    """schemas.incentive_schema.IncentiveEngine を満たす、B側(中身)の実装。

    allocate_and_pay 自体は「最高申告額が勝つ、支払いなし」という単純な規則にとどめる
    (信用枠の遵守チェック・制裁の適用は、このエンジンの外(deviation_test.py が
    compute_credit_limit の結果と申告を突き合わせて判定・記録する)。エンジンを
    信用枠と無関係な純関数に保つことで、「同一の観測に対して同じ結果を返す」という
    ①〜⑤の疎通確認上の性質(⑤検証層のcheck_boundary_type_match等)を、ケース1と
    同じ形で保てる。
    """

    def __init__(self, parameters: TriggerStrategyParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        if not declarations:
            return AllocationResult(allocated_agent_ids=[], payments={})
        winner = max(declarations, key=lambda d: (d.declared_value, d.agent_id))
        return AllocationResult(allocated_agent_ids=[winner.agent_id], payments={})


@dataclass
class CreditLimitResult:
    credit_limit: float
    in_punishment: bool
    rounds_since_last_violation: int | None
    """直近の違反からの経過ラウンド数。違反履歴が無ければNone。"""


def compute_credit_limit(
    env: EnvironmentClient,
    agent_id: str,
    round_id: int,
    params: TriggerStrategyParameters,
) -> CreditLimitResult:
    """agent_id の公開記録(CreditRoundRecord)だけから、round_id 時点の信用枠を導出する。

    読み取りは全員に公開されているため、誰でも同じ結果を再現できる(ケース1の
    compute_recent_win_rateと同じ思想)。round_id 時点の判定なので、round_id自身の
    記録はまだ存在しない(このラウンドの申告より前に呼ぶ)ことを前提とする。
    """
    records = sorted(
        (
            t
            for t in env.read_traces()
            if t.agent_id == agent_id and isinstance(t.payload, CreditRoundRecord)
        ),
        key=lambda t: t.round_id,
    )

    violations = [t for t in records if not t.payload.compliant]
    last_violation_round = violations[-1].round_id if violations else None

    if last_violation_round is not None:
        rounds_since = round_id - last_violation_round
        if rounds_since <= params.punishment_rounds:
            return CreditLimitResult(
                credit_limit=params.punishment_limit,
                in_punishment=True,
                rounds_since_last_violation=rounds_since,
            )
    else:
        rounds_since = None

    # 制裁期間中(punishment_limit近傍への強制的な自己制限)の遵守は、信用枠が実質
    # ゼロで「守るまでもなく守れている」だけなので、回復の実績としては数えない
    # (制裁明け直後に一気に信用枠が戻るのを防ぐ)。制裁明け後の遵守のみを加算対象にする。
    recovery_starts_after = (
        None if last_violation_round is None else last_violation_round + params.punishment_rounds
    )
    relevant = [
        t for t in records if recovery_starts_after is None or t.round_id > recovery_starts_after
    ]
    weighted_compliance = sum(env.trace_weight(t) for t in relevant)
    credit_limit = min(params.base_limit + params.growth_rate * weighted_compliance, params.max_limit)
    return CreditLimitResult(
        credit_limit=credit_limit, in_punishment=False, rounds_since_last_violation=rounds_since
    )
