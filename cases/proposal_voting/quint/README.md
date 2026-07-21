# Quint (TLAモード) 検証キット — ケース3(投票による共同意思決定)

動的安全性検証サブコンポーネント(`verification_layer_clarification.md` 2章)。
Quint/TLAは②収束性ではなく①到達可能性(+評価観点#16並行安全性、#23打ち切り耐性)を
担当する(`SMAS_theorymap.md` 2章の対応表)。

## `proposal_voting.qnt`

`cases/proposal_voting/langgraph_flow.py`の3ノード
(collect_rankings→aggregate→record)が表す、1ラウンドの実行フェーズ遷移を
状態機械として抽象化したモデル。ボルダ得点の算術そのもの(誰が勝つか)は対象外。

- **安全性(`validPhase`)**: phaseは常に`idle`/`collecting`/`aggregating`/`recorded`の
  いずれかに収まる(未定義の中間状態に落ちない)
  ```
  quint verify proposal_voting.qnt --main main --invariant validPhase
  ```
- **活性(`eventuallyRecords`)**: ラウンドを開始したら、いつか必ず`recorded`(=完走)に
  到達する(打ち切りルールがフォールバックで必ず結果を返す設計の裏付け、
  公平性を伴う時相論理、TLCバックエンドが必要)
  ```
  quint verify proposal_voting.qnt --main main --temporal eventuallyRecords --backend tlc
  ```

**既知の制約(D-19と同じ環境制約)**: この開発環境ではquint↔Apalache間のgRPCプロトコル
互換性バグにより`quint verify`が実行できない。`typecheck`・`quint run`(シミュレーション)
は確認済み。`generate_results_summary.py`の`run_quint_check()`が、ケース1・2と同じ方針で
シミュレーションによる経験的確認に留め、限界を明記する。

**既知の制約(D-19とは別の新しい環境不具合、D-29)**: `quint run`の**デフォルトバックエンド**
(初回自動ダウンロードされるRust評価器)は、このマシンでは展開後の実ファイル名
(`quint_evaluator.exe`)と起動コードが期待する名前(`quint-evaluator.exe`)が一致せず
`ENOENT`で失敗する。`--backend typescript`を明示指定すればRust評価器を経由せず問題ない
(`generate_results_summary.py`の`run_quint_check()`は元からこの指定をしており影響を
受けない)。バックエンド未指定でこのファイルを手元確認する場合のみ注意すること。
