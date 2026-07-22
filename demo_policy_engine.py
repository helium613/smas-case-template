"""(横断)アクセス制御「OPAポリシーエンジン」の目玉シーン(D-32→D-49)。

python demo_policy_engine.py で(リポジトリルートから)実行する。
事前に `opa` コマンドが必要(https://www.openpolicyagent.org/docs/latest/#running-opa)。

environment.pyのEnvironmentClient.write_traceは、壁(自領域のみ書き込み可)を
Python内のif文で直接判定している。このスクリプトは、同じルールを独立した
外部ポリシーエンジン(OPA)に問い合わせても、既存の壁判定と同じ結論に到達する
ことを確認する——「認可の執行点を外部ポリシーエンジンに切り出せるか」という
インタフェースの検証であり、environment.py側の実装を置き換えるものではない
(⑤検証層と同じ、実行パイプラインの外側からの監査、D-13/D-21/D-40)。

CI対象外(OPA未インストール環境でも例外で落ちずスキップする)。
"""
from __future__ import annotations

import sys

from pydantic import BaseModel

from environment import EnvironmentClient, WallViolation
from policy_engine import check_write_authorization, missing_opa_reason
from schemas.environment_schema import EnvironmentConfig, Trace


class _EmptyPayload(BaseModel):
    """このデモでは痕跡の中身自体は問わない(認可判定のみを検証する)ための最小payload。"""


def wall_allows(env: EnvironmentClient, writer_id: str, trace: Trace) -> bool:
    try:
        env.write_trace(writer_id=writer_id, trace=trace)
        return True
    except WallViolation:
        return False


def main() -> int:
    reason = missing_opa_reason()
    if reason:
        print(f"[SKIP] ポリシーエンジンの目玉シーンをスキップします: {reason}")
        return 0

    env_config = EnvironmentConfig(half_life_rounds=3.0, max_trace_age_rounds=20)

    cases = [
        ("alice", "alice", "自領域への書き込み(許可されるはず)"),
        ("bob", "alice", "他者領域への書き込み(拒否されるはず)"),
        ("carol", "carol", "自領域への書き込み(許可されるはず)"),
    ]

    print("--- 既存の壁判定(environment.py) と OPA(policy_engine.py) の決定を比較 ---\n")
    all_agree = True
    for writer_id, trace_agent_id, label in cases:
        env = EnvironmentClient(env_config)
        env.advance_round()
        trace = Trace(agent_id=trace_agent_id, round_id=env.current_round, payload=_EmptyPayload())

        wall_result = wall_allows(env, writer_id, trace)
        opa_result = check_write_authorization(writer_id, trace_agent_id)
        agree = wall_result == opa_result.allow
        all_agree = all_agree and agree

        print(f"--- {label}(writer_id={writer_id}, trace.agent_id={trace_agent_id}) ---")
        print(f"  既存の壁判定: {'許可' if wall_result else '拒否'}")
        print(f"  OPAの判定: {'許可' if opa_result.allow else '拒否'}")
        print(f"  一致?: {agree}")
        print()

    if all_agree:
        print("OPAが、既存の壁判定と同じ認可判断に独立に到達することを確認しました。")
    else:
        print("[WARN] OPAの判定が既存の壁判定と一致しないケースがありました。")
    return 0 if all_agree else 1


if __name__ == "__main__":
    sys.exit(main())
