module credit_allocation {
  // 信用枠配分(トリガー戦略)の状態機械を抽象化したモデル。
  // cases/credit_allocation/incentive_engine.py の compute_credit_limit が
  // 実装する「違反→制裁(punishmentRounds固定)→回復」の遷移を、具体的な
  // 信用枠の数値ではなく「制裁の残りラウンド数」という離散状態で表現する
  // (mdp_model.pyの状態設計と同じ抽象化)。

  const PUNISHMENT_ROUNDS: int

  var punishmentRemaining: int

  action init = all {
    punishmentRemaining' = 0,
  }

  // 通常時(punishmentRemaining=0)に遵守を続ける限り、制裁は発動しない。
  action comply = all {
    punishmentRemaining == 0,
    punishmentRemaining' = 0,
  }

  // 通常時に違反すると、満期(PUNISHMENT_ROUNDS)の制裁が始まる
  // (incentive_engine.compute_credit_limitの「違反直後はpunishment_limitに
  // 固定される」に対応)。
  action violate = all {
    punishmentRemaining == 0,
    punishmentRemaining' = PUNISHMENT_ROUNDS,
  }

  // 制裁中は、行動によらず1ラウンドごとに残り期間が減っていく
  // (CLAUDE.md 8章「フォールバックは申告内容に依存しない固定の挙動」と同じ原則。
  // 制裁中に何を申告しても、この遷移には影響しない)。
  action servePunishment = all {
    punishmentRemaining > 0,
    punishmentRemaining' = punishmentRemaining - 1,
  }

  action step = any {
    comply,
    violate,
    servePunishment,
  }

  // --- 安全性(invariant): quint verify --invariant で検証 -------------------

  // 制裁の残り期間は常に [0, PUNISHMENT_ROUNDS] の範囲に収まる
  // (負にならない、満期を超えて延びない)。
  val punishmentBound = punishmentRemaining >= 0 and punishmentRemaining <= PUNISHMENT_ROUNDS

  // --- 時相性質(liveness): quint verify --temporal --backend tlc で検証 -----
  // 「制裁が発動しても、いつか必ず通常状態(punishmentRemaining=0)に戻る」
  // という活性。ケース1のeventuallyTerminatesと同じく、公平性を伴う時相論理の
  // 検証が必要(TLCバックエンド、docs/DECISIONS.md D-19の環境制約が同様に適用される)。
  temporal eventuallyRecovers = eventually(punishmentRemaining == 0)
}

module main {
  import credit_allocation(PUNISHMENT_ROUNDS = 10).*
}
