module liquid_democracy {
  // 委任連鎖の解決(cases/liquid_democracy/incentive_engine.py の resolve_delegations)
  // を、1エージェントの視点から抽象化したモデル。連鎖を辿るたびにhopsTakenが増え、
  // MAX_DEPTHに達するか、直接投票者(または循環)に行き着くと停止する。

  const MAX_DEPTH: int

  var hopsTaken: int
  var status: str  // "following" | "resolved" | "voided"

  action init = all {
    hopsTaken' = 0,
    status' = "following",
  }

  // 委任先をさらに辿る(委任先がまた委任している場合)
  action hop = all {
    status == "following",
    hopsTaken < MAX_DEPTH,
    hopsTaken' = hopsTaken + 1,
    status' = "following",
  }

  // 直接投票者に行き着いた(resolve_delegationsが選択肢を確定する分岐)
  action resolve = all {
    status == "following",
    hopsTaken' = hopsTaken,
    status' = "resolved",
  }

  // MAX_DEPTHに達した(打ち切りルールと同じ思想。循環委任は通常この分岐で無効化される)
  action voidByDepth = all {
    status == "following",
    hopsTaken >= MAX_DEPTH,
    hopsTaken' = hopsTaken,
    status' = "voided",
  }

  action step = any {
    hop,
    resolve,
    voidByDepth,
  }

  // --- 安全性(invariant): quint verify --invariant で検証 -------------------

  // hopsTakenは常に[0, MAX_DEPTH]に収まる(負にならない、上限を超えない)。
  val hopsBound = hopsTaken >= 0 and hopsTaken <= MAX_DEPTH

  // statusは常にこの3状態のいずれか。
  val statusValid = status == "following" or status == "resolved" or status == "voided"

  // 上記2つをまとめた、run_quint_check()から呼ぶ単一の安全性チェック。
  val safety = hopsBound and statusValid

  // --- 時相性質(liveness): quint verify --temporal --backend tlc で検証 -----
  // 「委任の解決は、いつか必ずresolved(直接投票者に到達)かvoided(循環・深さ
  // 上限で無効化)のいずれかで終わる」という活性。無限に"following"のまま
  // ループし続けることがない、という打ち切り耐性(#23)の裏付け。
  temporal eventuallyTerminates = eventually(status == "resolved" or status == "voided")
}

module main {
  import liquid_democracy(MAX_DEPTH = 10).*
}
