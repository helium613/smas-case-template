"""⑤検証層(構造検証サブコンポーネント): 合成則(結合律・単位律)を事後チェックする。

検証的アプローチ(実装後にDisCoPyで確認)であり、事前の理論保証ではない
(CLAUDE.md 2章 原則5)。評価対象は「層をまたぐ接続の整合性」であり、
「エンジン内部の数式の正しさ」ではない(verification_layer_clarification.md 3.3節)。

このファイルは「そのまま使う」共通実装。ケースが変わっても①→③→②という
標準パイプラインの型シグネチャ自体は変わらない、という前提に立つ。
"""
from __future__ import annotations

from discopy.monoidal import Box, Diagram, Ty

from schemas.verification_schema import CompositionCheckResult, VerificationReport

# 各層の入出力を圏論の対象(Ty)として表現する。
Traces = Ty("Traces")
Declarations = Ty("Declarations")
Allocation = Ty("Allocation")


def build_pipeline() -> Diagram:
    """①→③→②→①(read→run→write)の標準パイプラインを構築する。

    discopy の `>>` は dom/cod が一致しない場合に例外を送出するため、
    この関数が例外なく戻ること自体が「層をまたぐ、入出力の型の連鎖が
    噛み合っている」ことの検証になる(境界の型一致チェック)。
    """
    read_traces = Box("read_traces", Traces, Declarations)
    allocate_and_pay = Box("allocate_and_pay", Declarations, Allocation)
    write_result_trace = Box("write_result_trace", Allocation, Traces)
    return read_traces >> allocate_and_pay >> write_result_trace


def check_boundary_type_match(build_fn=build_pipeline) -> CompositionCheckResult:
    """境界の型一致: パイプラインが構築できるか(discopyが自動的に保証する)。"""
    try:
        diagram = build_fn()
        return CompositionCheckResult(
            check_name="boundary_type_match", passed=True, detail=str(diagram)
        )
    except Exception as exc:  # noqa: BLE001
        return CompositionCheckResult(check_name="boundary_type_match", passed=False, detail=str(exc))


def check_associativity(diagram: Diagram) -> CompositionCheckResult:
    """結合律: (f>>g)>>h と f>>(g>>h) の dom/cod が一致するか。"""
    boxes = diagram.boxes
    if len(boxes) < 3:
        return CompositionCheckResult(
            check_name="associativity", passed=True, detail="対象boxが3未満のため自明に成立"
        )
    f, g, h = boxes[0], boxes[1], boxes[2]
    left = (f >> g) >> h
    right = f >> (g >> h)
    passed = left.dom == right.dom and left.cod == right.cod
    return CompositionCheckResult(
        check_name="associativity", passed=passed, detail=f"dom={left.dom} cod={left.cod}"
    )


def check_unitality(diagram: Diagram) -> CompositionCheckResult:
    """単位律: id_dom >> f と f >> id_cod が、元のdiagramと同じ dom/cod を保つか。"""
    identity_dom = Diagram.id(diagram.dom)
    identity_cod = Diagram.id(diagram.cod)
    left = identity_dom >> diagram
    right = diagram >> identity_cod
    passed = (left.dom, left.cod) == (diagram.dom, diagram.cod) == (right.dom, right.cod)
    return CompositionCheckResult(check_name="unitality", passed=passed)


def check_absence_of_concentrated_power(all_agent_ids: list[str], write_own_domain_only: bool) -> CompositionCheckResult:
    """権力集中の不在(評価観点#14): 特定の1主体が他主体の運命を一方的に決める
    権限を持っていないか。

    EnvironmentClient.write_trace の壁(自領域のみ書き込み可)が実際に守られて
    いる限り、この項目は構造的に成立する。write_own_domain_only は
    environment.EnvironmentClient.write_trace の実装がその制約を持つかを、
    呼び出し側(smoke_test等)が明示的に確認して渡す。
    """
    passed = write_own_domain_only and len(all_agent_ids) >= 1
    return CompositionCheckResult(
        check_name="absence_of_concentrated_power",
        passed=passed,
        detail=f"agents={all_agent_ids}",
    )


def run_structural_verification(
    all_agent_ids: list[str] | None = None, write_own_domain_only: bool = True
) -> VerificationReport:
    """①〜⑤の疎通確認で実行する、構造検証の最小セット。"""
    boundary_check = check_boundary_type_match()
    diagram = build_pipeline()
    checks = [
        boundary_check,
        check_associativity(diagram),
        check_unitality(diagram),
        check_absence_of_concentrated_power(all_agent_ids or [], write_own_domain_only),
    ]
    return VerificationReport(structural_checks=checks, all_passed=all(c.passed for c in checks))
