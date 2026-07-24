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

【ファンアウト対応、D-80】当初は「1エージェントにつき委任先は1人まで」という
v1の簡略化を置いていた(複数の送り手が1人の受け手に集中するファンインは
最初から動いたが、1人の送り手が複数の受け手に同時に配るファンアウトは
未対応だった)。A側(Declaration)は変更せず、**同じagent_idの複数の
Declarationを1ラウンドにまとめて提出する**ことでファンアウトを表現する
——1つのDeclarationは引き続き1つのdelegate_toしか持たない。この変更に伴い、
以下2点をファンアウト対応に一般化した:
- 循環検出: 出次数1以下を前提にした単純な連鎖追跡から、一般的なグラフの
  巡回検出(DFSベース)に置き換えた
- 保有額を超える委任の制約: 単一の宛先へのmin(宣言額, 保有額)ではなく、
  **全宛先への宣言額の合計**が保有額を超える場合、全宛先に按分(比例縮小)
  する——特定の宛先を優先する恣意的なルールを避け、公平・対称な取り扱いとした
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
    計算する。1エージェントが複数の宛先に同時に委任する(ファンアウト)場合も
    対応する(D-80)。

    支払いなし(liquid_democracy・privilege_delegationと同じ前例)。version・
    parametersを持ち、allocate_and_pay(declarations) -> AllocationResult を
    実装することで、既存のIncentiveEngineプロトコル・aggregation.run_mechanismに
    無変更で載る。
    """

    def __init__(self, parameters: PartialDelegationParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def _outgoing_edges(self, declarations: list[Declaration]) -> dict[str, list[tuple[str, float]]]:
        """agent_id -> [(委任先, 宣言額), ...]。同じagent_idの複数のDeclaration
        は、そのままこのリストに複数件並ぶ(ファンアウトの表現そのもの)。"""
        outgoing: dict[str, list[tuple[str, float]]] = {}
        for d in declarations:
            if d.delegate_to is not None:
                outgoing.setdefault(d.agent_id, []).append((d.delegate_to, d.declared_value))
        return outgoing

    def _all_agent_ids(
        self, declarations: list[Declaration], outgoing: dict[str, list[tuple[str, float]]]
    ) -> set[str]:
        ids = set(self.parameters.root_budgets) | {d.agent_id for d in declarations}
        for edges in outgoing.values():
            ids.update(target for target, _ in edges)
        return ids

    def find_cyclic_agents(self, declarations: list[Declaration]) -> set[str]:
        """循環委任(delegate_toを辿ると自分自身に戻ってくる)に含まれるエージェント
        の集合を返す。ファンアウト対応後は出次数が1を超えうるため、一般的な
        グラフの巡回検出(DFS、訪問中の経路に既にいるノードへ辿り着いたら
        そこから先を循環とみなす)を行う——単純な単一後続の連鎖追跡は使えない。

        循環委任は、金額計算(resolve_reachable_budgets)では**別扱い**にする——
        循環の中で金額が「公平に」いくら巡るべきかは現実の観点でも一意に定まらない
        (循環保証・round-tripping同様、金額の帳尻ではなく構造そのものが問題である
        ため)。したがって循環に含まれるエージェントの委任(全宛先分)には一切
        金額を流さず、循環の存在そのものを構造的リスクとして別途この関数で検出する。
        """
        outgoing = self._outgoing_edges(declarations)
        agent_ids = self._all_agent_ids(declarations, outgoing)
        cyclic: set[str] = set()
        visited: set[str] = set()

        def visit(node: str, path: list[str], on_path: set[str]) -> None:
            visited.add(node)
            path.append(node)
            on_path.add(node)
            for target, _ in outgoing.get(node, []):
                if target in on_path:
                    idx = path.index(target)
                    cyclic.update(path[idx:])
                elif target not in visited:
                    visit(target, path, on_path)
            path.pop()
            on_path.discard(node)

        for start in sorted(agent_ids):
            if start not in visited:
                visit(start, [], set())
        return cyclic

    def resolve_reachable_budgets(self, declarations: list[Declaration]) -> dict[str, float]:
        """各エージェントが実際に手元に残す金額(root_budgets + 委任経由の受取額
        − 自分がさらに委任した金額の合計)を、委任グラフのトポロジカル順に解決する。

        辺の向き: `declaration.delegate_to == P` というエージェントQの申告は、
        「QはPに、自分が保有する金額のうちdeclared_value分を委任する」ことを
        意味する。1人のQが複数のDeclarationを持てる(ファンアウト、D-80)ため、
        Qが実際に各宛先へ送れる金額は、**全宛先への宣言額の合計がQの手元にある
        金額を超える場合、全宛先に比例按分**する(特定の宛先を優先する恣意的な
        ルールを避けるため)。超えない場合は宣言どおり全額が届く。

        循環委任に含まれるエージェント(find_cyclic_agents参照)は、全ての
        出て行くedgeで金額を流さない——循環の外から流入する分だけを加算する。
        """
        cyclic_agents = self.find_cyclic_agents(declarations)
        outgoing = self._outgoing_edges(declarations)
        agent_ids = self._all_agent_ids(declarations, outgoing)

        sources_by_target: dict[str, set[str]] = {a: set() for a in agent_ids}
        for source, edges in outgoing.items():
            if source in cyclic_agents:
                continue
            for target, _ in edges:
                sources_by_target[target].add(source)
        in_degree: dict[str, int] = {a: len(sources_by_target[a]) for a in agent_ids}

        inflow: dict[str, float] = {a: 0.0 for a in agent_ids}
        net: dict[str, float] = {}
        frontier = [a for a in agent_ids if in_degree[a] == 0 and a not in cyclic_agents]
        depth = 0
        while frontier and depth < self.parameters.max_chain_depth:
            next_frontier: list[str] = []
            for node in frontier:
                gross = self.parameters.root_budgets.get(node, 0.0) + inflow[node]
                edges = outgoing.get(node, [])
                total_requested = sum(amount for _, amount in edges)
                scale = 1.0 if total_requested <= gross or total_requested <= 0.0 else gross / total_requested
                total_sent = 0.0
                targets_touched: set[str] = set()
                for target, amount in edges:
                    actual = amount * scale
                    inflow[target] += actual
                    total_sent += actual
                    targets_touched.add(target)
                net[node] = gross - total_sent
                for target in targets_touched:
                    if target not in cyclic_agents:
                        in_degree[target] -= 1
                        if in_degree[target] == 0:
                            next_frontier.append(target)
            frontier = next_frontier
            depth += 1

        # 循環に含まれるエージェント: 循環edge自体には金額を流さない(自分の
        # outgoing edgesは一切処理されない)が、循環の外からの流入は上のループで
        # 既にinflowへ加算済みなので、それをそのまま使う。
        for node in agent_ids:
            if node in cyclic_agents:
                net[node] = self.parameters.root_budgets.get(node, 0.0) + inflow[node]

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
