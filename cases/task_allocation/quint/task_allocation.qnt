module task_allocation {
  const AGENTS: Set[str]
  const MAX_ITERATIONS: int

  var declarations: str -> int
  var iteration: int
  var terminated: bool
  var fallbackUsed: bool

  action init = all {
    declarations' = AGENTS.mapBy(a => 0),
    iteration' = 0,
    terminated' = false,
    fallbackUsed' = false,
  }

  // ①環境層の壁: 引数agentで指定した領域にのみ書き込める(モデル上、
  // 「他者の領域に書く」遷移自体が存在しないことが壁の表現になる。
  // environment.EnvironmentClient.write_trace のWallViolationに対応)。
  action declare(agent: str, value: int): bool = all {
    not(terminated),
    declarations' = declarations.setBy(agent, old => value),
    iteration' = iteration,
    terminated' = terminated,
    fallbackUsed' = fallbackUsed,
  }

  // ②誘因構造エンジンの1回の試行(aggregation.run_mechanismのtry節に対応)。
  // 成功/失敗は非決定的に選ぶ(実際の失敗要因=タイムアウトや例外を抽象化)。
  action attempt = all {
    not(terminated),
    iteration < MAX_ITERATIONS,
    iteration' = iteration + 1,
    declarations' = declarations,
    any {
      all { terminated' = true, fallbackUsed' = false },
      all { terminated' = false, fallbackUsed' = fallbackUsed },
    },
  }

  // 打ち切り: 最大試行回数に達しても未終端ならフォールバックへ
  // (aggregation.run_mechanismのforループ終了後のフォールバック分岐に対応)。
  // フォールバックの発生条件は iteration のみに依存し、declarations の中身
  // (誰が何を申告したか)には一切依存しない — これが「打ち切りルール自体が
  // 新たな逸脱の温床にならない」(evaluation_criteria.md #23)の形式的な表現。
  action fallback = all {
    not(terminated),
    iteration >= MAX_ITERATIONS,
    terminated' = true,
    fallbackUsed' = true,
    declarations' = declarations,
    iteration' = iteration,
  }

  action step = any {
    all {
      nondet agent = AGENTS.oneOf()
      nondet value = 0.to(100).oneOf()
      declare(agent, value)
    },
    attempt,
    fallback,
  }

  // --- 安全性(invariant): quint verify --invariant で検証 -------------------

  // 打ち切りルールが暴走しない: 反復回数は常にMAX_ITERATIONS以下
  val iterationBound = iteration <= MAX_ITERATIONS

  // フォールバックは反復上限到達後にのみ発生する(申告内容に依存しない)
  val fallbackOnlyAfterExhaustion = fallbackUsed implies (iteration >= MAX_ITERATIONS)

  val safety = iterationBound and fallbackOnlyAfterExhaustion

  // --- 時相性質(liveness): quint verify --temporal --backend tlc で検証 -----
  // 「このラウンドはいつか必ず終端状態(成功またはフォールバック)に達する」
  // という活性(liveness)。Apalacheの有界モデル検査では公平性込みの活性を
  // 一般に扱えないため、TLCバックエンドで検証する(ユーザー指摘の通り)。
  temporal eventuallyTerminates = eventually(terminated)
}

module main {
  import task_allocation(AGENTS = Set("alice", "bob", "carol"), MAX_ITERATIONS = 3).*
}
