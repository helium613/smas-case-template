# Quint (TLAモード) 検証キット — ケース2(信用枠配分)

動的安全性検証サブコンポーネント(`verification_layer_clarification.md` 2章)。
Quint/TLAは②収束性ではなく①到達可能性(+評価観点#16並行安全性、#23打ち切り耐性)を
担当する(`SMAS_theorymap.md` 2章の対応表、ケース1振り返りD-19で確認済み)。

## `credit_allocation.qnt`

`cases/credit_allocation/incentive_engine.py`の`compute_credit_limit`が実装する
「違反→制裁(punishment_rounds固定)→回復」の遷移を、信用枠の具体的な数値ではなく
「制裁の残りラウンド数」という離散状態で抽象化したモデル。

- **安全性(`punishmentBound`)**: 制裁の残り期間が常に`[0, PUNISHMENT_ROUNDS]`に収まる
  ```
  quint verify credit_allocation.qnt --main main --invariant punishmentBound
  ```
- **活性(`eventuallyRecovers`)**: 制裁が発動しても、いつか必ず通常状態に戻る(公平性を
  伴う時相論理、TLCバックエンドが必要)
  ```
  quint verify credit_allocation.qnt --main main --temporal eventuallyRecovers --backend tlc
  ```

**既知の制約(D-19と同じ環境制約)**: この開発環境ではquint↔Apalache間のgRPCプロトコル
互換性バグにより`quint verify`が実行できない。`typecheck`・`quint run`(シミュレーション)
は確認済み。`generate_results_summary.py`の`run_quint_check()`が、ケース1と同じ方針で
シミュレーションによる経験的確認に留め、限界を明記する。
