"""(横断)アクセス制御: OPA(Open Policy Agent)によるポリシー評価(D-32→D-49)。

environment.pyのEnvironmentClient.write_traceは、壁(自領域のみ書き込み可)を
Python内のif文で直接判定している(WallViolation)。D-32は、本番実装ではこの種の
認可判定の執行点を、mTLS/JWT/DID等による識別性の検証(a)とは別に、OPA/Cedar等の
ポリシーエンジン(b)に切り出す、という方針だけを示していた。

このモジュールは、その方針を実際に動かして確認するインタフェース検証(D-49)。
environment.pyの壁判定を置き換えるものではない(実行パイプラインの単純さ・性能を
崩さない)——⑤検証層(verification.py)と同じ「横断的な監査」の位置づけで、外部
ポリシーエンジンが同じ認可判断に独立に到達できることを確認する(D-13/D-21/D-40と
同じ、実行パイプラインの外側)。

`opa eval`をsubprocessで呼ぶ(quintの統合パターン、D-19と同じ形)。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_POLICY_PATH = str(Path(__file__).resolve().parent / "policy" / "access_control.rego")


def missing_opa_reason() -> str | None:
    """`opa`コマンドが使える状態かを確認する。使えなければ理由文字列を返す
    (呼び出せる場合はNone)。目玉シーンのデモスクリプト側で、CI・未インストール
    環境でも例外で落ちずに「スキップ」できるようにするための、事前チェック用
    (agents/llm_real.pyのmissing_credentials_reason()と同じ設計)。
    """
    if shutil.which("opa") is None:
        return "opaコマンドが見つかりません(https://www.openpolicyagent.org/docs/latest/#running-opa)"
    return None


@dataclass
class PolicyDecision:
    allow: bool
    raw_output: str


def check_write_authorization(writer_id: str, trace_agent_id: str) -> PolicyDecision:
    """OPAに、writer_idがtrace_agent_id領域へ書き込む権限があるかを問い合わせる。

    environment.pyの壁判定(writer_id == trace.agent_id)と同じルールを、
    独立したポリシーエンジンの決定として再現する(policy/access_control.rego)。
    """
    input_data = {"writer_id": writer_id, "trace_agent_id": trace_agent_id}
    try:
        result = subprocess.run(
            [
                "opa", "eval",
                "--data", _POLICY_PATH,
                "--stdin-input",
                "--format", "json",
                "data.smas.access_control.allow",
            ],
            input=json.dumps(input_data),
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("opaコマンドが見つかりません") from exc
    if result.returncode != 0:
        raise RuntimeError(f"opa evalが失敗しました: {result.stderr}")
    parsed = json.loads(result.stdout)
    allow = parsed["result"][0]["expressions"][0]["value"]
    return PolicyDecision(allow=bool(allow), raw_output=result.stdout)
