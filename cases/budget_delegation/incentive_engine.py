"""②誘因構造層 B側: 部分委任・目減り型の予算委任チェーン(mechanism_catalog.md
ファミリー5「委任・権限移譲メカニズム」の3つ目の型、6ケース目実装の主眼)。

委任ファミリー内での既存2ケースとの決定的な違い(6ケース目実装の主眼、
docs/DECISIONS.md D-77/D-78以降の議論参照):

1. **ケース4(Liquid Democracy)は「重みの保存則」を持つ**(委任すると自分の
   投票権を手放す、合計は参加者数で一定)。**ケース5(IAM委任チェーン)は
   保存則が無い**(trustを与えても自分の権限は減らない、複製的構造)。
   **このケースは、委任元自身の残高は減る(保存的)が、委任先が受け取る
   金額は委任元の"全額"ではなく"一部"(委任元が選んだ額)である**、という
   両者とは異なる第3の型——委任は複製でも完全継承でもなく、**部分譲渡**。
   (実装上の教訓、D-78: 「保存的」と謳いながら実際には委任元のholdを一切
   減らさない実装ミスが最初にあり、循環委任で保有額が水増しされる
   「キックバック」という見かけ上の発見を生んでいた。ユーザーとの議論の結果、
   これは金額計算のバグであり、真に保存的な実装に修正した上で、循環委任
   そのものは別の構造的チェック(`find_cyclic_agents`)として扱う方針に決めた)。
2. **ケース5は到達可能な最大tierを返す(MAX集約)**。このケースは、複数の
   経路から委任される金額を**合計する(SUM集約)**——2人から同じ相手に
   委任が集まれば、その相手の保有額は単純に加算される(現実の金銭と同じ)。
3. **「誰も嘘をついていないのに、金額ではなく"想定される用途"がズレて伝播する」**
   という、ケース5のconfused deputyとは似て非なる望ましくない性質を実証する。
   委任元が「念のため多めに」委任した金額(over-provisioning)が、委任先の
   本来の用途に対して不釣り合いに大きい決済余地を生む——金額自体は虚偽でも
   何でもなく、各段階の判断は局所的に正当に見える。
"""
from __future__ import annotations

from pydantic import BaseModel

from schemas.incentive_schema import AllocationResult, Declaration


class PartialDelegationParameters(BaseModel):
    root_budgets: dict[str, float]
    """agent_id -> このエージェントが(委任を受けてではなく)本来独立に保有する予算。
    委任だけで予算を得るエージェントは0.0。"""

    intended_max_budget: dict[str, float]
    """agent_id -> 設計上、このエージェントの役割が実際に必要とする決済上限。
    root_budgetsより大きい値を許容する場合、それは「委任元が意図的に多めの
    決済余地を持たせている」ことを表す(例: 委任元自身は自分の全予算をそのまま
    保有してよい、intended_max_budget=root_budgetとする)。"""

    max_chain_depth: int = 10
    """委任チェーンの最大解決段数(打ち切りルール、CLAUDE.md 8章)。委任グラフを
    トポロジカル順(委任元→委任先)に解決するため、この段数を超えて深い
    チェーンは、それ以上先の解決を打ち切る(root_budgetsのみの値で止まる)。"""


class PartialDelegationEngine:
    """予算委任グラフをトポロジカル順に解決し、各エージェントが実際に手元に
    残す金額(root_budgets + 委任で受け取った金額 − 自分がさらに委任した金額)を
    計算する。

    支払いなし(liquid_democracy・privilege_delegationと同じ前例)。version・
    parametersを持ち、allocate_and_pay(declarations) -> AllocationResult を
    実装することで、既存のIncentiveEngineプロトコル・aggregation.run_mechanismに
    無変更で載る。
    """

    def __init__(self, parameters: PartialDelegationParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def find_cyclic_agents(self, declarations: list[Declaration]) -> set[str]:
        """循環委任(delegate_toを辿ると自分自身に戻ってくる)に含まれるエージェント
        の集合を返す。

        1エージェントにつき委任先は1人まで(出次数1以下)という制約があるため、
        循環は必ず「その中の全員が同じ輪に含まれる単純な輪」になる(delegate_to
        を辿って自分自身に戻ってくるかを見るだけで判定できる)。

        循環委任は、金額計算(resolve_reachable_budgets)では**別扱い**にする——
        循環の中で金額が「公平に」いくら巡るべきかは現実の観点でも一意に定まらない
        (循環保証・round-tripping同様、金額の帳尻ではなく構造そのものが問題である
        ため)。したがって循環に含まれるedgeには一切金額を流さず(委任は不成立
        として扱う)、循環の存在そのものを構造的リスクとして別途この関数で検出する。
        """
        delegate_to = {d.agent_id: d.delegate_to for d in declarations if d.delegate_to is not None}
        agent_ids = (
            set(self.parameters.root_budgets)
            | {d.agent_id for d in declarations}
            | set(delegate_to.values())
        )
        cyclic: set[str] = set()
        for start in agent_ids:
            if start in cyclic:
                continue
            path: list[str] = []
            seen: set[str] = set()
            current: str | None = start
            while current is not None and current not in seen:
                seen.add(current)
                path.append(current)
                current = delegate_to.get(current)
            if current is not None and current in seen:
                idx = path.index(current)
                cyclic.update(path[idx:])
        return cyclic

    def resolve_reachable_budgets(self, declarations: list[Declaration]) -> dict[str, float]:
        """各エージェントが実際に手元に残す金額(root_budgets + 委任経由の受取額
        − 自分がさらに委任した金額)を、委任グラフのトポロジカル順に解決する。

        辺の向き: `declaration.delegate_to == P` というエージェントQの申告は、
        「QはPに、自分が保有する金額のうちdeclared_value分を委任する」ことを
        意味する(1対1、1エージェントにつき委任先は1人までのv1簡略化。ケース5の
        TrustDeclaringAgentと同じ制約)。Pが実際に受け取れる金額は
        min(Qのdeclared_value, Qの手元にある金額)——委任元が保有する以上の
        金額は委任できない(ケース5のtier継承には無い、実額ならではの制約)。

        循環委任に含まれるエージェント(find_cyclic_agents参照)は、循環edge
        そのものには金額を流さない——循環の外から流入する分だけを加算する。
        """
        cyclic_agents = self.find_cyclic_agents(declarations)
        delegate_to = {d.agent_id: d.delegate_to for d in declarations if d.delegate_to is not None}
        declared_value = {d.agent_id: d.declared_value for d in declarations}
        agent_ids = (
            set(self.parameters.root_budgets)
            | {d.agent_id for d in declarations}
            | set(delegate_to.values())
        )

        incoming: dict[str, list[str]] = {a: [] for a in agent_ids}
        in_degree: dict[str, int] = {a: 0 for a in agent_ids}
        for source, target in delegate_to.items():
            if source in cyclic_agents:
                continue  # 循環edgeは金額を流さない(circular round-tripping扱い)
            incoming[target].append(source)
            in_degree[target] += 1

        sent: dict[str, float] = {a: 0.0 for a in agent_ids}
        net: dict[str, float] = {}
        frontier = [a for a in agent_ids if in_degree[a] == 0 and a not in cyclic_agents]
        depth = 0
        while frontier and depth < self.parameters.max_chain_depth:
            next_frontier: list[str] = []
            for node in frontier:
                inflow = sum(sent[j] for j in incoming[node])
                gross = self.parameters.root_budgets.get(node, 0.0) + inflow
                target = delegate_to.get(node)
                sent[node] = min(declared_value.get(node, 0.0), gross) if target is not None else 0.0
                net[node] = gross - sent[node]
                if target is not None and target not in cyclic_agents:
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        next_frontier.append(target)
            frontier = next_frontier
            depth += 1

        # 循環に含まれるエージェント: 循環の外からの流入のみを加算する(循環edge
        # 自体には金額を流さないため、自分自身への"キックバック"は発生しない)。
        for node in agent_ids:
            if node in cyclic_agents:
                inflow = sum(sent[j] for j in incoming[node])
                net[node] = self.parameters.root_budgets.get(node, 0.0) + inflow

        # max_chain_depthで打ち切られ未解決のまま残ったノード(深いチェーンの末端)は
        # root_budgetsのみを保持しているものとして扱う。
        for node in agent_ids:
            net.setdefault(node, self.parameters.root_budgets.get(node, 0.0))

        return net

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        """allocated_agent_ids = 意図された上限(intended_max_budget)を超えて
        手元に残ってしまったエージェントの一覧(=想定外の決済余地が生まれた
        エージェント、他ケースの"勝者"に相当)。paymentsは支払い概念が無いため
        常に{}。

        循環委任そのもの(find_cyclic_agents)はここには含めない——金額の
        超過とは別の、構造的リスクとして別途検出する(D-78)。
        """
        net = self.resolve_reachable_budgets(declarations)
        escalated = [
            agent_id
            for agent_id, amount in net.items()
            if amount > self.parameters.intended_max_budget[agent_id] + 1e-9
        ]
        return AllocationResult(allocated_agent_ids=escalated, payments={})
