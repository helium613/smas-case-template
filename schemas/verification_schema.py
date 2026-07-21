"""⑤検証層 A側: 型定義のみ。

検証層は複数の検証手段を束ねる層(構造検証/動的安全性検証/実証的検証/収束検証、
verification_layer_clarification.md 2章)。ここでは構造検証(verification.py)の
結果を表す型のみを持つ。
"""
from __future__ import annotations

from pydantic import BaseModel


class CompositionCheckResult(BaseModel):
    """合成則チェック1件分の結果。"""

    check_name: str
    passed: bool
    detail: str = ""


class VerificationReport(BaseModel):
    """構造検証層の実行結果。DisCoPy・Quintのチェック結果Pass/Failとして、
    5大指標の⑤検証可能性の根拠になる(CLAUDE.md 10章)。
    """

    structural_checks: list[CompositionCheckResult]
    all_passed: bool
