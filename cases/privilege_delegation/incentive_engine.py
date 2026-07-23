"""②誘因構造層 B側: IAM委任チェーンの権限昇格(mechanism_catalog.md ファミリー5、
「閾値署名・マルチシグ的な権限分散」の隣に位置する、委任・権限移譲メカニズムの
第2実装)。

ケース4(Liquid Democracy)との決定的な違いは2点(5ケース目実装の主眼、
docs/DECISIONS.md 参照):

1. **重みの保存則が無い**。Liquid Democracyは「委任すると自分の投票権を手放す」
   (委任元+委任先の合計が常に参加者数と一致)。IAMのtrust関係(AssumeRole)は
   「与えても自分の権限は減らない」——委任元は委任先が増えるだけで、自分の権限は
   そのまま。③集約層の前提が初めて変わるケース。
2. **単一終点への解決ではなく、到達可能性(reachability)の計算**。
   `LiquidDemocracyEngine.resolve_delegations`は各エージェントを単一の実効投票先に
   解決するが、AssumeRoleチェーンは「そのエージェントがtrustを辿って最終的に
   到達できる最大権限」という到達可能集合の計算が必要(グラフの到達可能性、
   単一パスの終点探索とは異なるアルゴリズム)。

このケースが実証する「望ましくない性質」も他ケースと異なる: 単一エージェントの
戦略的な虚偽申告ではなく、**複数の個別には正当な信頼宣言が合成されることで、
誰も意図していない権限昇格経路が生まれる**(confused deputy、実務で頻出する
実害カテゴリ)。
"""
from __future__ import annotations

from pydantic import BaseModel

from schemas.incentive_schema import AllocationResult, Declaration


class PrivilegeDelegationParameters(BaseModel):
    tiers: dict[str, int]
    """agent_id -> 素の権限tier(そのエージェントが直接保有するリソースの機密度)。"""

    intended_max_tier: dict[str, int]
    """agent_id -> 設計上到達を許容する上限tier。tiers以上の値を許容する場合、
    それは「意図された正当な多段委任」を表す(例: ビルドサービスが最終的に
    デプロイ権限まで到達することは設計上許容する、等)。"""

    max_chain_depth: int = 10
    """委任(trust)チェーンの最大深さ。打ち切りルール(CLAUDE.md 8章)と同じ思想を
    到達可能性探索の粒度で適用する: 循環trust(相互信頼)があっても無限ループに
    ならないよう、探索の深さを機械的に打ち切る。"""


class PrivilegeDelegationEngine:
    """AssumeRole型の信頼グラフを解決し、各エージェントが到達可能な最大tierを計算する。

    支払いなし(liquid_democracyと同じ前例)。version・parametersを持ち、
    allocate_and_pay(declarations) -> AllocationResult を実装することで、
    既存のIncentiveEngineプロトコル・aggregation.run_mechanismに無変更で載る。
    """

    def __init__(self, parameters: PrivilegeDelegationParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def reachable_agent_ids(self, declarations: list[Declaration], start_agent_id: str) -> set[str]:
        """start_agent_idが(直接・間接に)assumeできる全エージェントを返す(自分自身を含む)。

        辺の向き: `declaration.delegate_to == P` というエージェントQの申告は、
        「QはPからassumeされることを信頼する」、すなわち「PはQをassumeできる
        (Qの権限を借りられる)」という有向辺(P→Q)を意味する。Pから到達可能な
        集合は、Pが直接assumeできる相手を起点に、その相手が"さらにassumeできる
        相手"を再帰的にたどる(assumeしたIDでさらに連鎖できる、実際のAssumeRole
        チェーンと同じ多段委任)。訪問済み集合でループを防止し、max_chain_depthで
        打ち切る。

        `resolve_reachable_tiers`(tierの要約値のみ返す)の内部計算を公開したもの。
        `analysis.py`のchokepoint分析・blast radius計算等、具体的な到達先の一覧
        そのものを必要とする事後/事前チェックから再利用する。
        """
        by_delegate_to: dict[str, list[str]] = {}
        for d in declarations:
            if d.delegate_to is not None:
                by_delegate_to.setdefault(d.delegate_to, []).append(d.agent_id)

        visited = {start_agent_id}
        frontier = [start_agent_id]
        depth = 0
        while frontier and depth < self.parameters.max_chain_depth:
            next_frontier = []
            for node in frontier:
                for nxt in by_delegate_to.get(node, []):
                    if nxt not in visited:
                        visited.add(nxt)
                        next_frontier.append(nxt)
            frontier = next_frontier
            depth += 1
        return visited

    def resolve_reachable_tiers(self, declarations: list[Declaration]) -> dict[str, int]:
        """各エージェントが到達可能な最大tierを計算する(`reachable_agent_ids`の要約)。"""
        return {
            agent_id: max(self.parameters.tiers[n] for n in self.reachable_agent_ids(declarations, agent_id))
            for agent_id in self.parameters.tiers
        }

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        """allocated_agent_ids = 意図された上限(intended_max_tier)を超えて到達
        できてしまったエージェントの一覧(=権限昇格が成立したエージェント、
        他ケースの"勝者"に相当)。paymentsは支払い概念が無いため常に{}。
        """
        reachable = self.resolve_reachable_tiers(declarations)
        escalated = [
            agent_id
            for agent_id, tier in reachable.items()
            if tier > self.parameters.intended_max_tier[agent_id]
        ]
        return AllocationResult(allocated_agent_ids=escalated, payments={})
