# smas-case-template

SMAS(戦略的多主体協調系, Strategic Multi-Agent System)の1ケースを実装するための
テンプレートリポジトリ。GitHubの `Use this template` でforkし、下記「このケース
について」を埋めてから実装を始める。

設計原則の全体像は [`CLAUDE.md`](./CLAUDE.md)、理論的背景は [`docs/`](./docs) を
参照。特に迷ったら `CLAUDE.md` 12章「迷ったときの判断基準」を見ること。

## このケースについて

<!-- fork後にここを埋める -->

- ケース名:
- 検証するメカニズム:
- 何を確認したいか:

## セットアップ

```bash
pip install -r requirements.txt
python smoke_test.py   # ①〜⑤の疎通を確認する
```

## ディレクトリ構成(責務分離版、CLAUDE.md 4章に対応)

| 責務層 | ファイル | このテンプレートでの状態 |
|---|---|---|
| (横断)A側 型定義 | `schemas/` | 共通実装。**そのまま使う**(変更頻度が上がったら設計を見直す、CLAUDE.md 11章) |
| ストレージ層(①環境層) | `environment.py` | 共通実装。**そのまま使う** |
| メカニズム定義層(②誘因構造層) | `engine/incentive_engine.py` | **ここだけケースごとに書く**。サンプルとして1財セカンドプライス(VCGの最小特殊形)を同梱 |
| メカニズム実行層(③集約層) | `aggregation.py` | 共通実装。打ち切りルール(最大試行回数・タイムアウト・フォールバック)実装済み、`pref_voting`利用の投票集約ヘルパーも同梱 |
| 主体決定層(④実行主体層) | `agents/` | 雛形。`rule_based.py` / `llm_mock.py` はそのまま使える。`llm_real.py` はAPIキー設定が必要 |
| 構造検証層(⑤検証層) | `verification.py` | 共通実装。`DisCoPy`で①→③→②パイプラインの合成則を事後チェック |
| 逸脱注入シナリオ | `scenarios/deviation_test.py` | 配線+シーン3(修正)の最小サンプル実装済み。当選率の閾値等の判定基準はケースごとに調整・差し替える |
| 検証キット | `verification_kit/` | `montecarlo.py`・`mdp_convergence.py` は共通実装。`quint/` は案件ごとに `.qnt` を追加 |
| パラメータ | `config.yaml` | 構造は共通、値はケースごとに調整する |

## フォーク後にやること(チェックリスト)

1. `engine/incentive_engine.py` を、このケースの誘因構造(配分ルール+支払いルールを
   不可分な1つの仕様として)で書き換える。**都度の数学的導出が必要な、唯一の層**
2. 必要なら `schemas/incentive_schema.py` の `Declaration` / `AllocationResult` を
   拡張する(**A側の変更は理由をコミットメッセージに明記する**、CLAUDE.md 11章。
   B側が増えるたびにA側の書き換えが頻発する場合は設計上の危険信号、
   `smas_implementation_spec_for_cursor.md` 13章)
3. `scenarios/deviation_test.py` / `engine/incentive_engine.py` の
   `filter_eligible_declarations`(信用ゲートの最小サンプル)を、このケース固有の
   逸脱パターンと「修正された」と判定する基準に差し替える。**シーン3実装時、特定の1関数が全員の
   運命を一方的に決める「隠れた中央集権」が紛れ込んでいないか、必ず目視確認する**
4. `config.yaml` の値をこのケースに合わせて調整する
5. `python smoke_test.py` で①〜⑤の疎通を確認する

## 新規ケースが既存の骨格に収まるかの判定基準(関手による対応づけ)

「このケースの①環境層・②誘因構造層それぞれの型定義が、`schemas/` の型を
満たしているか」という機械的チェックのみで判定する
(`verification_layer_clarification.md` 3.4節)。委任連鎖の結合律検証は、
1回性・単一段階のケースでは原理的に検証不可能であり、委任・時間発展を含む
ケースで初めて実施できる。

## フレームワーク統合時の3項目チェックリスト(LangGraph等を使う場合)

1. 状態の実体は①環境層(`EnvironmentClient`)にあるか。フレームワークのState等は
   参照のみを持つか(データの実体を直接持たせない)
2. 壁(アクセス制御、`EnvironmentClient.write_trace` が自領域のみ書き込みを許す
   制約)はフレームワークを迂回されていないか
3. フレームワークのオーケストレーション(ノード実行順序)が②③⑤の役割
   (誘因構造・集約・検証)に越境していないか

## 評価の測り方(5大指標を主役にする)

レポート・ログ出力は5大指標を主役にし、24項目の評価観点(`docs/evaluation_criteria.md`)
はその内訳・根拠として1行併記する(省略しない、`docs/roadmap_consistency_memo.md` 3.1節)。

| 大指標 | 測定方法 | このテンプレートでの実装 |
|---|---|---|
| ①到達可能性 | Yes/No判定 | `verification.check_absence_of_concentrated_power` 等 |
| ②収束性 | MDPの収束確率(1回性エンジンでは適用不可) | `verification_kit/mdp_convergence.py` |
| ③頑健性 | モンテカルロ結果の要約 | `verification_kit/montecarlo.py` |
| ④資源コスト | 計算量・実行時間の概算 | `aggregation.AggregationOutcome.elapsed_seconds` |
| ⑤検証可能性 | DisCoPy・Quintのチェック結果Pass/Fail | `verification.run_structural_verification` |

## 絶対に守るべき設計原則

このリポジトリで作業する際は、必ず [`CLAUDE.md`](./CLAUDE.md) の
「2. 絶対に守るべき設計原則」を確認すること。
