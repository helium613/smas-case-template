# smas-case-template

SMAS(戦略的多主体協調系, Strategic Multi-Agent System)のアーキテクチャパターンを、
複数のケースで実装・検証するリポジトリ。当初はケースごとにforkするテンプレートとして
構想したが、1ケース目の実装が実質的にこのリポジトリで進んだ実態を追認し、**単一
リポジトリ内で共通実装とケース固有実装を`cases/`ディレクトリで分離する方針**に変更した
(`docs/DECISIONS.md` D-23)。詳細は[`docs/repository_structure.md`](./docs/repository_structure.md)。

設計原則の全体像は [`CLAUDE.md`](./CLAUDE.md)、理論的背景は [`docs/`](./docs) を
参照。特に迷ったら `CLAUDE.md` 12章「迷ったときの判断基準」を見ること。

## ケース一覧

| ケース | ディレクトリ | メカニズム | 状態 |
|---|---|---|---|
| 1. タスク配分 | [`cases/task_allocation/`](./cases/task_allocation) | VCG(セカンドプライス、1回性) | 完走(`git tag case1-task-allocation-complete`) |
| 2. 信用枠配分 | [`cases/credit_allocation/`](./cases/credit_allocation) | トリガー戦略(限定的懲罰、繰り返しゲーム、支払いなし) | 完走(4シーン構成、MDP・モンテカルロ・介入ポート実行使を含む) |
| 3. 投票による共同意思決定 | [`cases/proposal_voting/`](./cases/proposal_voting) | ボルダ得点(投票、支払いなし、非耐戦略性) | 完走(2シーン構成、LangGraph実地検証・意図的な非耐戦略性の実証を含む) |
| 4. Liquid Democracy | [`cases/liquid_democracy/`](./cases/liquid_democracy) | 委任民主主義(委任連鎖、支払いなし) | 完走(3シーン構成、循環委任の検出・重みの保存則・#19の初検証を含む) |

## セットアップ

```bash
pip install -r requirements.txt
python cases/task_allocation/smoke_test.py   # ①〜⑤の疎通を確認する(全ケース共通の実行方法)
```

## ディレクトリ構成(責務分離版、CLAUDE.md 4章に対応)

| 責務層 | ファイル | 位置づけ |
|---|---|---|
| (横断)A側 型定義 | `schemas/` | 共通実装(リポジトリルート)。**そのまま使う**(変更頻度が上がったら設計を見直す、CLAUDE.md 11章) |
| ストレージ層(①環境層) | `environment.py` | 共通実装(リポジトリルート)。**そのまま使う** |
| メカニズム定義層(②誘因構造層) | `cases/<ケース名>/incentive_engine.py` | **ここだけケースごとに書く**。都度の数学的導出が必要な、唯一の層 |
| メカニズム実行層(③集約層) | `aggregation.py` | 共通実装(リポジトリルート)。打ち切りルール(最大試行回数・タイムアウト・フォールバック)実装済み、`pref_voting`利用の投票集約ヘルパーも同梱 |
| 主体決定層(④実行主体層) | `agents/` | 共通実装(リポジトリルート)。`rule_based.py` / `llm_mock.py` / `optimization_based.py` はそのまま使える。`llm_real.py` はAPIキー設定が必要 |
| (横断)構造検証 | `verification.py` | 共通実装(リポジトリルート)。`DisCoPy`で①〜④の型接続(合成則)を事後監査する。①〜④のような実行順序を持つパイプラインの一部ではない(D-13/D-21/D-40、CLAUDE.md 4章) |
| 逸脱注入シナリオ | `cases/<ケース名>/deviation_test.py` | ケースごとに書く。判定基準(効用差の計算方法等)はケースの性質に合わせる |
| 検証キット(共通部分) | `verification_kit/montecarlo.py`・`mdp_convergence.py`・`gambit_collusion.py` | 共通実装(リポジトリルート) |
| 検証キット(Quint) | `cases/<ケース名>/quint/` | ケースごとの状態機械を記述するため、ケース固有 |
| パラメータ | `cases/<ケース名>/config.yaml` | 構造は`schemas/environment_schema.py`で共通、値はケースごとに調整する |
| 可視化(ケース横断) | `visualize/` | 共通実装(リポジトリルート)。4ケース共通の5層パイプラインや5大指標ダッシュボードなど、ケースをまたぐ視点の可視化。Reactなし・npmなし、バニラJS+SVGの単一HTMLファイル |
| 可視化(ケース固有) | `cases/<ケース名>/visualize/` | ケースごとに書く。例: `cases/liquid_democracy/visualize/delegation_resolver.html`(委任連鎖の解決過程) |

## 新しいケースを追加する手順

1. `cases/<ケース名>/`ディレクトリを新設する
2. `cases/task_allocation/`を参考に、`incentive_engine.py`(②、唯一都度の数学的導出が必要な層)・`deviation_test.py`・`config.yaml`・`smoke_test.py`・`generate_results_summary.py`を書く。共通実装(`environment.py`・`aggregation.py`・`verification.py`・`schemas/`・`agents/`・`verification_kit/montecarlo.py`・`mdp_convergence.py`)はリポジトリルートのものをそのままimportする
3. 必要なら `schemas/` を拡張する(**A側の変更は理由をコミットメッセージに明記する**、CLAUDE.md 11章。B側が増えるたびにA側の書き換えが頻発する場合は設計上の危険信号、`smas_implementation_spec_for_cursor.md` 13章)
4. `python cases/<ケース名>/smoke_test.py` で①〜⑤の疎通を確認する。`smoke_test.py`を置くだけでCI(`.github/workflows/smoke-test.yml`)が自動的にこのケースを対象に含める
5. 共通部分に変更を加える場合は、既存の全ケース(`cases/*/smoke_test.py`)を実行して後方互換性を確認する

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

レポート・ログ出力は5大指標を主役にし、25項目の評価観点(`docs/evaluation_criteria.md`)
はその内訳・根拠として1行併記する(省略しない、`docs/roadmap_consistency_memo.md` 3.1節)。

| 大指標 | 測定方法 | 共通実装 |
|---|---|---|
| ①到達可能性 | Yes/No判定 | `verification.check_absence_of_concentrated_power` 等 |
| ②収束性 | MDPの収束確率(1回性エンジンでは適用不可) | `verification_kit/mdp_convergence.py` |
| ③頑健性 | モンテカルロ結果の要約(+結託耐性は`pygambit`でナッシュ均衡を検証) | `verification_kit/montecarlo.py`・`gambit_collusion.py` |
| ④資源コスト | 計算量・実行時間の概算 | `aggregation.AggregationOutcome.elapsed_seconds` |
| ⑤検証可能性 | DisCoPy・Quintのチェック結果Pass/Fail | `verification.run_structural_verification`、各ケースの`quint/` |

各ケースの`generate_results_summary.py`が、このフォーマットで`cases/<ケース名>/results/summary.md`を生成する。

## 絶対に守るべき設計原則

このリポジトリで作業する際は、必ず [`CLAUDE.md`](./CLAUDE.md) の
「2. 絶対に守るべき設計原則」を確認すること。
