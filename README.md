# smas-reference-architecture

SMAS(戦略的多主体協調系, Strategic Multi-Agent System)——中央の執行者を置かず、
環境を介した間接的な作用で協調と逸脱修正を実現する多主体系——について、
**非中央集権的協調が成立するための3性質(誘因整合性・耐戦略性・個人合理性)を
5層構造として設計し、層間の型接続の整合性を機械的に検証しつつ、実行時の
安全性・収束性も実証する、アーキテクチャパターンとその検証方法論**を提示する
リファレンス実装。構想(`docs/`の設計ドキュメント群)から、性質の異なる5つの
具体ケースによる実証的裏付け、可視化・意思決定支援ツールまでを1つのリポジトリに
まとめている。

当初はケースごとにforkするテンプレートとして構想したが、1ケース目の実装が
実質的にこのリポジトリで進んだ実態を追認し、**単一リポジトリ内で共通実装と
ケース固有実装を`cases/`ディレクトリで分離する方針**に変更した(`docs/DECISIONS.md`
D-23。リポジトリ名も、この実態(単なるテンプレートではなくリファレンス実装)に
合わせて`smas-case-template`から改称した)。詳細は
[`docs/repository_structure.md`](./docs/repository_structure.md)。

設計原則の全体像は [`CLAUDE.md`](./CLAUDE.md)、理論的背景は [`docs/`](./docs) を
参照。特に迷ったら `CLAUDE.md` 12章「迷ったときの判断基準」を見ること。
設計判断の変遷は [`docs/DECISIONS.md`](./docs/DECISIONS.md)(追記専用のログ、D-01〜)を参照。

## ケース一覧

5つのケースは、メカニズムファミリー(支払いあり/なし、1回性/繰り返し、投票/委任等)を
意図的に変えながら、同じ5層構造がどこまで無変更で使い回せるかを実証する。

| ケース | ディレクトリ | メカニズム | 状態 |
|---|---|---|---|
| 1. タスク配分 | [`cases/task_allocation/`](./cases/task_allocation) | VCG(セカンドプライス、1回性) | 完走(`git tag case1-task-allocation-complete`) |
| 2. 信用枠配分 | [`cases/credit_allocation/`](./cases/credit_allocation) | トリガー戦略(限定的懲罰、繰り返しゲーム、支払いなし) | 完走(4シーン構成、MDP・モンテカルロ・介入ポート実行使を含む) |
| 3. 投票による共同意思決定 | [`cases/proposal_voting/`](./cases/proposal_voting) | ボルダ得点(投票、支払いなし、非耐戦略性) | 完走(2シーン構成、LangGraph実地検証・意図的な非耐戦略性の実証を含む) |
| 4. Liquid Democracy | [`cases/liquid_democracy/`](./cases/liquid_democracy) | 委任民主主義(委任連鎖、支払いなし) | 完走(3シーン構成、循環委任の検出・重みの保存則・#19の初検証を含む) |
| 5. IAM委任チェーンの権限昇格 | [`cases/privilege_delegation/`](./cases/privilege_delegation) | AssumeRole型信頼グラフの到達可能性(委任・権限移譲、支払いなし) | 完走(3シーン構成。**誰も虚偽申告していないのに、複数の正直な宣言の合成が権限昇格を生む**「confused deputy」という、他4ケースとは異なる種類の望ましくない性質を実証。chokepointランキング・候補trust宣言の総当たりスキャン・blast radius計算という3種の意思決定支援ツールを同梱、D-60〜D-70) |

ケース5は、SMASと隣接する別アーキタイプ「信頼委任システム」との境界を検討する
過程で生まれた(詳細は[`docs/architecture_family_map.md`](./docs/architecture_family_map.md) 2.6節)。

## セットアップ

```bash
pip install -r requirements.txt
python cases/task_allocation/smoke_test.py   # ①〜⑤の疎通を確認する(全ケース共通の実行方法)
```

## 可視化・意思決定支援ツール

[`visualize/index.html`](./visualize/index.html) が全ての可視化(ケース横断+ケース
固有)への入り口。ブラウザで直接開ける、単一HTMLファイル群(Reactなし・npmなし、
バニラJS+SVG)。

- **ケース横断**: [`visualize/cross_case.html`](./visualize/cross_case.html)(5大指標×ケース、実行主体層別ダッシュボード、評価観点25項目、レポート全文ビューア。現状ケース1〜4のみ対応、ケース5の統合は未着手、D-66)、[`visualize/incentive_gradient.html`](./visualize/incentive_gradient.html)(申告値・戦略の強さをスイープした効用カーブで「制度の穴」を可視化、D-56)
- **ケース固有**: 各ケースの実際に発生したシーンの推移(`scenario_timeline.html`)、委任・trust関係のグラフ構造(`delegation_resolver.html`・`trust_graph.html`)。ケース5には、`cases/privilege_delegation/analysis.py`(chokepointランキング・候補trust宣言の総当たりスキャン・blast radius計算)という、事後分析+事前チェック+インシデント対応の意思決定支援ツールも同梱(D-64/D-65/D-70)

## ディレクトリ構成(責務分離版、CLAUDE.md 4章に対応)

| 責務層 | ファイル | 位置づけ |
|---|---|---|
| (横断)A側 型定義 | `schemas/` | 共通実装(リポジトリルート)。**そのまま使う**(変更頻度が上がったら設計を見直す、CLAUDE.md 11章) |
| ストレージ層(①環境層) | `environment.py` | 共通実装(リポジトリルート)。**そのまま使う** |
| メカニズム定義層(②誘因構造層) | `cases/<ケース名>/incentive_engine.py` | **ここだけケースごとに書く**。都度の数学的導出が必要な、唯一の層 |
| メカニズム実行層(③集約層) | `aggregation.py` | 共通実装(リポジトリルート)。打ち切りルール(最大試行回数・タイムアウト・フォールバック)実装済み、`pref_voting`利用の投票集約ヘルパーも同梱 |
| 主体決定層(④実行主体層) | `agents/` | 共通実装(リポジトリルート)。`rule_based.py` / `llm_mock.py` / `optimization_based.py` はそのまま使える。`llm_real.py` はAPIキー設定が必要 |
| (横断)構造検証 | `verification.py` | 共通実装(リポジトリルート)。`DisCoPy`で①〜④の型接続(合成則)を事後監査する。①〜④のような実行順序を持つパイプラインの一部ではない(D-13/D-21/D-40、CLAUDE.md 4章) |
| (横断)アクセス制御 | `policy_engine.py`・`policy/access_control.rego` | 共通実装(リポジトリルート)。D-32の方針(認可はOPA/Cedar等が担う)を実際にOPAで組み込んだインタフェース検証。`environment.py`の壁判定(`EnvironmentClient.write_trace`)は置き換えず、⑤検証層と同じ「実行パイプラインの外側」の監査として独立に動作する(D-49) |
| 逸脱注入シナリオ | `cases/<ケース名>/deviation_test.py` | ケースごとに書く。判定基準(効用差の計算方法等)はケースの性質に合わせる |
| 検証キット(共通部分) | `verification_kit/montecarlo.py`・`mdp_convergence.py`・`gambit_collusion.py`・`information_asymmetry.py` | 共通実装(リポジトリルート)。`information_asymmetry.py`は同一ラウンド内で他者の申告が見えないことを実行時に検証する`LeakDetectingAgent`(D-59) |
| 検証キット(Quint) | `cases/<ケース名>/quint/` | ケースごとの状態機械を記述するため、ケース固有 |
| パラメータ | `cases/<ケース名>/config.yaml` | 構造は`schemas/environment_schema.py`で共通、値はケースごとに調整する |
| 可視化(ケース横断) | `visualize/` | 共通実装(リポジトリルート)。5層パイプラインや5大指標ダッシュボードなど、ケースをまたぐ視点の可視化。`visualize/index.html`が全可視化への入り口(D-66)。`visualize/embed_reports.py`は各ケースの`results/summary.md`全文を機械的に埋め込む(手転記しない、D-52) |
| 可視化(ケース固有) | `cases/<ケース名>/visualize/` | ケースごとに書く。例: `cases/liquid_democracy/visualize/delegation_resolver.html`(委任連鎖の解決過程、1ラウンドの内部処理)、`cases/credit_allocation/visualize/scenario_timeline.html`(4シーンデモの全38ラウンドの推移、複数ラウンドにわたる実行プロセス) |
| 意思決定支援ツール(ケース固有) | `cases/<ケース名>/analysis.py` | ①〜⑤の実行パイプラインには含まれない、事後分析・事前チェック・インシデント対応用ユーティリティ。現状ケース5のみ(`rank_chokepoint_edges`・`scan_candidate_trust_grants`・`compute_blast_radius`、D-64/D-65/D-70) |

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
25項目に収まらない性質(例: ケース5の「confused deputy」)が見つかった場合は、
安易に新項目を横並び追加せず、既存項目の下位種類として位置づけられないかを
まず検討する(D-68)。

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
