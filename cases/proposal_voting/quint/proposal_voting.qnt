module proposal_voting {
  // 投票による共同意思決定(ボルダ得点)のラウンド進行を抽象化したモデル。
  // ボルダ得点の算術そのもの(誰が勝つか)はQuintの対象外(検証層は「層をまたぐ
  // 接続の整合性」を見るのであって「エンジン内部の数式の正しさ」は見ない、
  // CLAUDE.md 2章 原則5)。ここでは cases/proposal_voting/langgraph_flow.py の
  // 3ノード(collect_rankings→aggregate→record)が表す、1ラウンドの実行フェーズ
  // 遷移を状態機械として表現する。

  var phase: str

  action init = all {
    phase' = "idle",
  }

  // ④実行主体層: 申告収集(langgraph_flow.collect_rankings_node に対応)
  action collect = all {
    phase == "idle",
    phase' = "collecting",
  }

  // ③集約層: run_mechanism経由で②を呼ぶ(langgraph_flow.aggregate_node に対応)
  action aggregate = all {
    phase == "collecting",
    phase' = "aggregating",
  }

  // ①環境層: 参加記録の書き込み(langgraph_flow.record_node に対応)
  action record = all {
    phase == "aggregating",
    phase' = "recorded",
  }

  // 次のラウンドへ(idleに戻る)
  action resetRound = all {
    phase == "recorded",
    phase' = "idle",
  }

  action step = any {
    collect,
    aggregate,
    record,
    resetRound,
  }

  // --- 安全性(invariant): quint verify --invariant で検証 -------------------

  // phaseは常にこの4状態のいずれかに収まる(未定義の中間状態に落ちない)。
  val validPhase = phase == "idle" or phase == "collecting" or phase == "aggregating" or phase == "recorded"

  // --- 時相性質(liveness): quint verify --temporal --backend tlc で検証 -----
  // 「ラウンドを開始したら、いつか必ずrecorded(=①③④を経て完走)に到達する」
  // という活性。③集約層の打ち切りルール(CLAUDE.md 8章)がフォールバックで
  // 必ず結果を返す設計になっていることの、状態機械レベルでの裏付け。
  temporal eventuallyRecords = eventually(phase == "recorded")
}

module main {
  import proposal_voting.*
}
