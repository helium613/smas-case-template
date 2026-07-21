# SMASプロジェクト リポジトリ構成(最終案)

## 全体像: 3リポジトリ構成

```
1. smas-architecture        (A: 仕様・ドキュメント本体)
2. smas-case-template       (テンプレート: 新ケース着手時にforkする土台)
3. smas-case-<個別名>        (B: テンプレートからforkした、各ケースの実装)
   例: smas-case-task-allocation, smas-case-delegation
```

---

## 1. smas-architecture(仕様・ドキュメント中心)

```
smas-architecture/
├── README.md                  # プロジェクト全体の概要、①②(構想・概念)の内容
├── docs/
│   ├── 01_concept.md          # ①中核3性質(誘因整合性・耐戦略性・個人合理性)+前提背景
│   ├── 02_five_layers.md      # 5層構造の説明
│   ├── 03_guideline.md        # コア/拡張の区分ガイドライン
│   ├── 04_evaluation.md       # 評価観点22項目
│   └── glossary.md            # 日英用語集
├── schemas/                    # 各層のインターフェース仕様(型定義のみ、実行しない)
│   ├── environment_schema.py   # 痕跡・壁の型(Pydantic)
│   ├── incentive_schema.py     # 誘因構造エンジンの入出力インターフェース
│   ├── agent_schema.py         # 実行主体層のdecide()インターフェース
│   └── verification_schema.py  # 検証層が扱う合成則の型
└── LICENSE                     # CC BY 4.0等、オープンな参照実装として
```

**役割**: 「このパターンとは何か」を定義する規格書。実行可能なプログラム本体は持たず、型定義とドキュメントのみ。ケースが増えてもここは基本的に変化しない。

---

## 2. smas-case-template(GitHub Template Repository)

```
smas-case-template/
├── README.md                   # [このケースは何を検証するか]を書く欄(空欄前提)
├── config.yaml                 # ①環境層のパラメータ(痕跡の寿命・減衰率等)
├── environment.py              # ①環境層: 共通実装(そのまま使う)
├── aggregation.py              # ③集約層: 共通コード(VCG系はscipy割当解、投票系はpref_voting)
├── verification.py             # ⑤検証層: DisCoPy利用の共通コード(そのまま使う)
├── engine/
│   └── incentive_engine.py     # ②誘因構造エンジン: 【ここだけケースごとに書く】
├── agents/
│   ├── rule_based.py           # ④実行主体: ルールベース(雛形、微修正で使う)
│   ├── llm_mock.py             # ④実行主体: LLMモック(確率分布、雛形)
│   └── llm_real.py             # ④実行主体: LLM実物(Tool Use/JSON Schema、雛形)
├── scenarios/
│   └── deviation_test.py       # 逸脱注入テストのシナリオ【ケースごとに書く】
└── verification_kit/            # 独立した検証キット(前回合意した構成)
    ├── quint/                   # 並行性・安全性検証(TLAモード)
    └── mdp_convergence.py       # 収束確率評価(pymdptoolbox)
```

**役割**: 「何が共通(そのまま使う)で、何がケース固有(埋める)か」を、フォルダ構造そのもので体現する土台。GitHubの"Use this template"機能でfork前提。

---

## 3. smas-case-task-allocation(1ケース目、テンプレートからfork)

```
smas-case-task-allocation/
├── README.md                   # 「これはタスク配分ケースの検証です」+結果サマリー
├── config.yaml                 # このケース用のパラメータ値
├── engine/
│   └── incentive_engine.py     # VCG支払い関数を実装(埋めた状態)
├── agents/
│   └── (テンプレートからほぼそのまま、必要な差分のみ調整)
├── scenarios/
│   └── deviation_test.py       # 過大申告のシナリオ等、埋めた状態
├── verification_kit/
│   └── (実行済みの検証結果: 収束率97%等の出力ログを含む)
└── results/
    └── summary.md               # 「N=1000試行で収束率○%」等の最終サマリー
```

---

## 4. (将来・任意)smas-presentation(可視化ビューア、ケース非依存)

```
smas-presentation/
├── README.md                   # 「SMASのログ形式に沿ったデータを可視化するビューア」
├── src/                         # TS/React、DisCoPy由来のワイヤリングダイアグラム表示等
└── log_format_spec.md           # smas-architectureのschemasと対応する、ログ出力フォーマット仕様
```

**役割**: ①環境層のログ出力フォーマットが標準化された段階(2ケース目着手時が目安)で切り出す。1ケース目では`smas-case-task-allocation`内に直接書いて構わない。

---

## 依存関係の全体図

```
smas-architecture (仕様: schemas/を参照)
        ↑ 準拠
smas-case-template (仕様に準拠した雛形)
        ↑ fork
smas-case-task-allocation, smas-case-delegation, ... (個別ケース)
        ↓ ログ出力(共通フォーマット)
smas-presentation (任意・将来: 汎用ビューア)
```

## 運用ルールの要点

- **smas-architectureへの変更は稀**(①②③概念層・骨格層はほぼ普遍という前提のため)
- **smas-case-templateへの変更は、複数ケースをこなす中で「これも共通化できる」と気づいた時のみ**(前回合意した"2ケース目で骨格を検証する"というプロセスの受け皿)
- **各smas-case-*は独立して育ち、他のケースに影響を与えない**
