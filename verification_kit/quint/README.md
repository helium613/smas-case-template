# Quint (TLAモード) 検証キット

動的安全性検証サブコンポーネント(並行性・打ち切り安全性、
`verification_layer_clarification.md` 2章)の置き場所。

Quintは独立したツール([`@informalsystems/quint`](https://quint-lang.org/))で
あり、Pythonライブラリではないため `requirements.txt` には含まれない。

```bash
npm install -g @informalsystems/quint
```

## 対応する大指標(SMAS_theorymap.md 2章の対応表どおり)

Quint/TLAは**②収束性ではなく①到達可能性**(+評価観点#16並行安全性、#23打ち切り耐性)を
担当する。②収束性はMDP(Python、`verification_kit/mdp_convergence.py`)の担当であり、
かつ1回性VCG(今回の1ケース目)には理論上適用対象外(`SMAS_theorymap.md` 2.1節)。

①到達可能性はさらに性質の種類で使い分ける:
- **安全性(safety)**: 「反復回数は上限を超えない」「フォールバックは反復上限到達後にのみ
  発生する(申告内容に依存しない)」→ SMTベースの**Apalache**(既定バックエンド)
  `quint verify task_allocation.qnt --main main --invariant safety`
- **活性(liveness)**: 「このラウンドは公平なスケジューリングの下で必ず終端に達する」→
  公平性を伴う網羅的な時相論理検証が必要で、**TLC**バックエンドの本領
  `quint verify task_allocation.qnt --main main --temporal eventuallyTerminates --backend tlc`

## `task_allocation.qnt`

1ケース目(タスク配分・VCG)の①環境層(壁)と③集約層(打ち切りルール)を、
`aggregation.run_mechanism`・`environment.EnvironmentClient` の抽象化として
状態遷移で記述したもの。`quint typecheck`・`quint run`(シミュレーション)は
このリポジトリの開発環境で確認済み。

**既知の制約(D-19)**: このリポジトリの開発環境では、quint(0.31.0)のgRPCクライアントと
Apalacheサーバー(0.51.1)の間のプロトコル互換性バグ(`@grpc/proto-loader`の記述子パース)
により、`quint verify`(Apalache・TLCどちらのバックエンドも)が実行できない。
`generate_results_summary.py`の`run_quint_check()`は、代わりにシミュレータ
(`quint run --invariant safety`)による有限サンプルの経験的確認に留めている。
`.qnt`自体はtypecheck済みのため、環境が修復され次第、上記コマンドの再実行のみで
Apalache/TLCによる網羅的検証に切り替えられる。
