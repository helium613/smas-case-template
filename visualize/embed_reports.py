"""visualize/cross_case.html の「レポート全文」タブに埋め込む、4ケース分の
results/summary.md の生テキストを機械的に更新するビルドスクリプト(D-52)。

python visualize/embed_reports.py で(リポジトリルートから)実行する。

タブ2(5大指標ダッシュボード)の「▸ 詳細」は、各ケースのsummary.mdの該当
パラグラフを人手でほぼそのまま転記したもの(D-43)。それに対しこのスクリプトは、
判断の余地が無い「生テキストそのものの埋め込み」に限定して機械化する——
手計算・手転記でデータを埋め込むと転記ミスが起きる、という教訓(D-41の
scenario_timeline.htmlバグ)を、このケースでも踏まえる。

各ケースのsummary.mdをJSON文字列としてエンコードして埋め込む(バッククォート・
${}等、JSのテンプレートリテラルを壊す文字がsummary.md中のMarkdownコード
スパン(`agents/...`等)に頻出するため、素朴なテンプレートリテラル埋め込みは
壊れる。JSON.parseで復元する方が確実)。
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HTML_PATH = _REPO_ROOT / "visualize" / "cross_case.html"

_CASES = [
    ("task_allocation", "cases/task_allocation/results/summary.md"),
    ("credit_allocation", "cases/credit_allocation/results/summary.md"),
    ("proposal_voting", "cases/proposal_voting/results/summary.md"),
    ("liquid_democracy", "cases/liquid_democracy/results/summary.md"),
]

_START_MARKER = "/* REPORTS_DATA_START (visualize/embed_reports.py が機械的に更新する、手編集禁止) */"
_END_MARKER = "/* REPORTS_DATA_END */"


def main() -> None:
    reports = {}
    for case_id, rel_path in _CASES:
        text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
        reports[case_id] = text

    entries = ",\n".join(
        f"    {json.dumps(case_id, ensure_ascii=False)}: {json.dumps(text, ensure_ascii=False)}"
        for case_id, text in reports.items()
    )
    block = f"{_START_MARKER}\n  var REPORTS = {{\n{entries}\n  }};\n  {_END_MARKER}"

    html = _HTML_PATH.read_text(encoding="utf-8")
    start_idx = html.find(_START_MARKER)
    end_idx = html.find(_END_MARKER)
    if start_idx == -1 or end_idx == -1:
        raise RuntimeError(f"マーカーが見つかりません: {_HTML_PATH} に {_START_MARKER} を追加してください")
    end_idx += len(_END_MARKER)
    new_html = html[:start_idx] + block + html[end_idx:]
    _HTML_PATH.write_text(new_html, encoding="utf-8")
    print(f"{_HTML_PATH} のREPORTSデータを{len(reports)}ケース分更新しました。")


if __name__ == "__main__":
    main()
