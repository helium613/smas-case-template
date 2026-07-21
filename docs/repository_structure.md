# SMASプロジェクト リポジトリ構成

## 現行方針: 単一リポジトリ+`cases/`ディレクトリ(`docs/DECISIONS.md` D-23)

1ケース目(タスク配分)は、後述の「旧3リポジトリ構成案」が想定していたテンプレートリポジトリに直接実装され、実質的にテンプレートとケース実装が同一リポジトリで運用された。2ケース目(信用枠配分)着手にあたり、この実態を追認し、**新しいGitHubリポジトリは作らず、単一リポジトリ内で共通部分とケース固有部分を`cases/`ディレクトリで分離する**方針に正式変更した。

```
smas-case-template/(このリポジトリ。名称は残すが実態は「共通実装+全ケース」)
├── environment.py              # ①: 共通実装(そのまま使う)
├── aggregation.py              # ③: 共通実装(VCG系はscipy割当解、投票系はpref_voting)
├── verification.py             # ⑤: DisCoPy利用の共通実装
├── schemas/                    # 型定義(A側、共通)
│   ├── environment_schema.py
│   ├── incentive_schema.py
│   ├── agent_schema.py
│   └── verification_schema.py
├── agents/                     # ④: 共通実装(ルールベース/LLMモック/LLM実物)
│   ├── rule_based.py
│   ├── llm_mock.py
│   └── llm_real.py
├── verification_kit/           # 検証キット: ケース非依存部分のみ共通
│   ├── montecarlo.py           # ③頑健性(どのIncentiveEngineにも使える)
│   └── mdp_convergence.py      # ②収束性(状態遷移を持つケース向け、共通ユーティリティ)
├── .github/workflows/
│   └── smoke-test.yml          # cases/*/smoke_test.py を全件自動実行
├── docs/                       # 仕様・設計判断ログ(DECISIONS.md含む)
├── CLAUDE.md                   # 行動指針(唯一、ルート直下に置く)
└── cases/
    ├── task_allocation/        # ケース1(タスク配分・VCG、1回性)
    │   ├── incentive_engine.py         # ②: 【ここだけケースごとに書く】
    │   ├── deviation_test.py           # 逸脱注入シナリオ【ケースごとに書く】
    │   ├── config.yaml                 # このケース用のパラメータ値
    │   ├── smoke_test.py               # 疎通確認(CI対象)
    │   ├── generate_results_summary.py # 5大指標レポート生成
    │   ├── demo_llm_real.py            # LLM実物の目玉シーン(CI対象外)
    │   ├── quint/                      # このケース固有のQuint(TLA)スペック
    │   │   ├── task_allocation.qnt
    │   │   └── README.md
    │   └── results/
    │       └── summary.md              # 生成された検証結果サマリー
    └── credit_allocation/      # ケース2(信用枠配分、繰り返しゲーム)、以降同じ構成
```

### 共通/ケース固有の判断基準

| 分類 | 該当ファイル | 判断基準 |
|---|---|---|
| 共通(リポジトリルート) | `environment.py`・`aggregation.py`・`verification.py`・`schemas/`・`agents/`・`verification_kit/montecarlo.py`・`verification_kit/mdp_convergence.py` | ケースが変わっても型・ロジックが変わらない(1ケース目完走の振り返りで、Initial commit以降無変更だったことを確認済み) |
| ケース固有(`cases/<ケース名>/`) | `incentive_engine.py`・`deviation_test.py`・`config.yaml`・`smoke_test.py`・`generate_results_summary.py`・`demo_llm_real.py`・`quint/`・`results/` | メカニズムの中身、パラメータ値、デモの筋書きがケースごとに異なる |

### 運用ルール

- **共通部分の修正は、このリポジトリのルート(正典)に対して行う**。修正後、`cases/*/smoke_test.py`を全て実行し、既存ケースへの後方互換性を確認する
- **ケースの追加は`cases/<ケース名>/`ディレクトリを新設するだけで良い**。`smoke_test.py`さえ置けばCI(`smoke-test.yml`)が自動的に対象に含める
- **ケース完走時点は`git tag`で参照可能にする**(例: `case1-task-allocation-complete`)。ケース固有ファイルを後から変更しても、完走時点の状態は履歴からいつでも参照できる
- 「共通部分をパッケージ化して各ケースにバージョン管理された依存として配る」ような重い仕組みは、現状のスクラッチ規模(数ケース)では過剰投資と判断し、採用しない。手動コピー運用がケース3以降で本当に辛くなったら、その時に再検討する(先回りしない、CLAUDE.mdの一貫した方針)

---

## 不採用となった旧3リポジトリ構成案(参考)

以下は1ケース目着手前に検討していた案。実際には採用されず、上記の単一リポジトリ構成に置き換わった。

```
1. smas-architecture        (A: 仕様・ドキュメント本体)
2. smas-case-template       (テンプレート: 新ケース着手時にforkする土台)
3. smas-case-<個別名>        (B: テンプレートからforkした、各ケースの実装)
   例: smas-case-task-allocation, smas-case-delegation
```

**smas-architecture**(仕様・ドキュメント中心): `schemas/`(型定義のみ、実行しない)とdocsを持ち、ケースが増えても変化しない規格書という位置づけだった。

**smas-case-template**(GitHub Template Repository): `environment.py`・`aggregation.py`・`verification.py`・`agents/`が共通実装、`engine/incentive_engine.py`・`scenarios/deviation_test.py`がケースごとに書く空欄、という構成だった。

**smas-case-<ケース名>**(各ケースの具体実装): テンプレートをforkし、`engine/incentive_engine.py`等を埋めた状態で運用する想定だった。

**不採用の理由**: 1ケース目の実装が、想定されていた「テンプレート」リポジトリに直接書かれ、この3層構造が実態と乖離した。振り返ると、単一リポジトリ+`git log`によるほうが「共通部分がどれだけ変更されずに済んだか」を直接的に検証でき(2つのリポジトリを手動でdiffするより確実)、手動バックポート時の同期ズレリスクも発生しない。詳細は`docs/DECISIONS.md` D-23。
