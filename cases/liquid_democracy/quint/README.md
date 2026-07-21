# Quint (TLAモード) 検証キット — ケース4(Liquid Democracy)

動的安全性検証サブコンポーネント(`verification_layer_clarification.md` 2章)。
Quint/TLAは②収束性ではなく①到達可能性(+評価観点#16並行安全性、#23打ち切り耐性)を
担当する(`SMAS_theorymap.md` 2章の対応表)。

## `liquid_democracy.qnt`

`cases/liquid_democracy/incentive_engine.py`の`resolve_delegations`が実装する
「委任先を辿る→直接投票者に到達(resolved)、または深さ上限・循環で無効化(voided)」
という遷移を、1エージェント視点の委任連鎖の解決過程として抽象化したモデル。

- **安全性(`safety` = `hopsBound and statusValid`)**: 辿った回数は常に`[0, MAX_DEPTH]`に
  収まり、statusは常に`following`/`resolved`/`voided`のいずれか
  ```
  quint verify liquid_democracy.qnt --main main --invariant safety
  ```
- **活性(`eventuallyTerminates`)**: 委任の解決は、いつか必ず`resolved`か`voided`で
  終わる(無限に`following`のままループし続けることがない、打ち切り耐性#23の裏付け、
  公平性を伴う時相論理、TLCバックエンドが必要)
  ```
  quint verify liquid_democracy.qnt --main main --temporal eventuallyTerminates --backend tlc
  ```

**既知の制約(D-19と同じ環境制約)**: この開発環境ではquint↔Apalache間のgRPCプロトコル
互換性バグにより`quint verify`が実行できない。`typecheck`・`quint run`(シミュレーション、
`--backend typescript`)は確認済み。`generate_results_summary.py`の`run_quint_check()`が、
ケース1〜3と同じ方針でシミュレーションによる経験的確認に留め、限界を明記する。

**既知の制約(D-19とは別の環境不具合、D-29)**: `quint run`の**デフォルトバックエンド**
(Rust評価器)は、このマシンではファイル名の不一致で`ENOENT`になる。
`--backend typescript`を明示指定すれば問題ない(`run_quint_check()`は元からこの指定)。
