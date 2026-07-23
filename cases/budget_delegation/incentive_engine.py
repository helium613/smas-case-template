"""②誘因構造層 B側: 部分委任・目減り型の予算委任チェーン(mechanism_catalog.md
ファミリー5「委任・権限移譲メカニズム」の3つ目の型、6ケース目実装の主眼)。

委任ファミリー内での既存2ケースとの決定的な違い(6ケース目実装の主眼、
docs/DECISIONS.md D-77以降の議論参照):

1. **ケース4(Liquid Democracy)は「重みの保存則」を持つ**(委任すると自分の
   投票権を手放す、合計は参加者数で一定)。**ケース5(IAM委任チェーン)は
   保存則が無い**(trustを与えても自分の権限は減らない、複製的構造)。
   **このケースは、委任元自身の残高は減る(保存的)が、委任先が受け取る
   金額は委任元の"全額"ではなく"一部"(委任元が選んだ額)である**、という
   両者とは異なる第3の型——委任は複製でも完全継承でもなく、**部分譲渡**。
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
    """委任チェーンの最大反復回数(打ち切りルール、CLAUDE.md 8章)。循環委任
    (相互委任)があっても、金額は各段階でmin(宣言額, 保有額)に制約されるため
    有限値に単調増加で収束するが、念のため反復回数を打ち切る。"""


class PartialDelegationEngine:
    """予算委任グラフを反復的に解決し、各エージェントが実際に保有しうる金額
    (root_budgets + 委任で受け取った金額の合計)を計算する。

    支払いなし(liquid_democracy・privilege_delegationと同じ前例)。version・
    parametersを持ち、allocate_and_pay(declarations) -> AllocationResult を
    実装することで、既存のIncentiveEngineプロトコル・aggregation.run_mechanismに
    無変更で載る。
    """

    def __init__(self, parameters: PartialDelegationParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def resolve_reachable_budgets(self, declarations: list[Declaration]) -> dict[str, float]:
        """各エージェントが保有しうる金額(root_budgets + 委任経由の受取額の合計)を
        反復的に解決する。

        辺の向き: `declaration.delegate_to == P` というエージェントQの申告は、
        「QはPに、自分が保有する金額のうちdeclared_value分を委任する」ことを
        意味する(1対1、1エージェントにつき委任先は1人までのv1簡略化。ケース5の
        TrustDeclaringAgentと同じ制約)。Pが実際に受け取れる金額は
        min(Qのdeclared_value, Qがその時点で保有する金額)——委任元が保有する
        以上の金額は委任できない(ケース5のtier継承には無い、実額ならではの制約)。

        反復のたびに1ホップ分だけ金額が伝播するため、max_chain_depth回の反復で
        多段の委任チェーンが収束する。保有額は反復ごとに単調非減少かつ有限の
        上限(全root_budgetsの合計+全declared_valueの合計)で頭打ちになるため、
        循環委任があっても発散せず必ず収束する。
        """
        agent_ids = (
            set(self.parameters.root_budgets)
            | {d.agent_id for d in declarations}
            | {d.delegate_to for d in declarations if d.delegate_to is not None}
        )
        declared_value = {d.agent_id: d.declared_value for d in declarations}
        delegate_to = {d.agent_id: d.delegate_to for d in declarations}

        held = {a: self.parameters.root_budgets.get(a, 0.0) for a in agent_ids}
        for _ in range(self.parameters.max_chain_depth):
            inflow = {a: 0.0 for a in agent_ids}
            for source in agent_ids:
                target = delegate_to.get(source)
                if target is None:
                    continue
                passed = min(declared_value.get(source, 0.0), held[source])
                inflow[target] += passed
            held = {a: self.parameters.root_budgets.get(a, 0.0) + inflow[a] for a in agent_ids}
        return held

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        """allocated_agent_ids = 意図された上限(intended_max_budget)を超えて
        保有できてしまったエージェントの一覧(=想定外の決済余地が生まれた
        エージェント、他ケースの"勝者"に相当)。paymentsは支払い概念が無いため
        常に{}。
        """
        held = self.resolve_reachable_budgets(declarations)
        escalated = [
            agent_id
            for agent_id, amount in held.items()
            if amount > self.parameters.intended_max_budget[agent_id] + 1e-9
        ]
        return AllocationResult(allocated_agent_ids=escalated, payments={})
