"""②誘因構造層 B側: Liquid Democracy(委任民主主義、mechanism_catalog.md ファミリー5)。

投票と委任のハイブリッドという、ケース1(VCG、支払いあり)・ケース2(トリガー戦略、
繰り返しゲーム)・ケース3(ボルダ得点、非耐戦略性の実証)のいずれとも異なる性質の
実証(D-30)。あえて二択・単純多数決という、それ自体は耐戦略性を満たす集計方式を
選ぶ——集計方式の操作可能性はケース3がすでに実証済みであり、このケースの主眼は
「委任構造そのものが新しい問題(循環委任・重みの保存則)を持ち込むか」であって、
集計方式の耐戦略性を再度問うと論点がぼやけるため(D-30)。

評価観点#19(委任連鎖を通した誘因構造の伝播の妥当性)は、このケースで初めて
実地検証される(プロジェクト開始以来、一度も検証されていなかった横断的評価観点)。
"""
from __future__ import annotations

from pydantic import BaseModel

from schemas.incentive_schema import AllocationResult, Declaration


class LiquidDemocracyParameters(BaseModel):
    choices: list[str] = ["yes", "no"]
    max_delegation_depth: int = 10
    """委任連鎖の最大深さ。打ち切りルール(CLAUDE.md 8章)と同じ思想を、連鎖解決の
    粒度で適用する: 深すぎる連鎖(通常は循環の兆候)は、申告内容に依存しない固定の
    挙動(無効票)としてフォールバックし、無限ループを起こさない。"""


class LiquidDemocracyEngine:
    """委任連鎖を解決し、実効投票を重み付き単純多数決で集計する(支払いなし)。"""

    def __init__(self, parameters: LiquidDemocracyParameters, version: str = "1.0.0") -> None:
        self.parameters = parameters
        self.version = version

    def resolve_delegations(self, declarations: list[Declaration]) -> dict[str, str | None]:
        """各エージェントの実効投票先(直接投票の選択肢、または委任先を辿った先の
        選択肢)を解決する。循環委任・連鎖の深さ上限に達した場合は None(無効票)。

        戻り値はagent_id→選択肢(または無効ならNone)。②誘因構造層の内部計算
        そのものであり、これが「委任連鎖を通した誘因構造の伝播」(#19)の実体。
        """
        by_agent = {d.agent_id: d for d in declarations}
        resolved: dict[str, str | None] = {}

        def resolve(agent_id: str, path: tuple[str, ...]) -> str | None:
            if agent_id in resolved:
                return resolved[agent_id]
            if agent_id in path:
                for voided in path[path.index(agent_id):]:
                    resolved[voided] = None
                return None
            declaration = by_agent.get(agent_id)
            if declaration is None or declaration.delegate_to is None:
                choice = declaration.declared_ranking[0] if declaration and declaration.declared_ranking else None
                resolved[agent_id] = choice
                return choice
            if len(path) >= self.parameters.max_delegation_depth:
                resolved[agent_id] = None
                return None
            result = resolve(declaration.delegate_to, path + (agent_id,))
            resolved.setdefault(agent_id, result)
            return result

        for agent_id in by_agent:
            resolve(agent_id, ())
        # resolvedには、実在しない委任先(declare_toの誤字・離脱済みagent_id等)への
        # 参照が中間結果として紛れ込みうる(D-31で発見)。戻り値は実際に申告した
        # エージェントのみに絞り、重みの保存則(len(resolved)==総申告者数)が
        # 常に成立するようにする。
        return {agent_id: resolved[agent_id] for agent_id in by_agent}

    def allocate_and_pay(self, declarations: list[Declaration]) -> AllocationResult:
        resolved = self.resolve_delegations(declarations)
        tally = {c: 0 for c in self.parameters.choices}
        for choice in resolved.values():
            if choice in tally:
                tally[choice] += 1
        winner = max(self.parameters.choices, key=lambda c: tally[c])
        return AllocationResult(allocated_agent_ids=[winner], payments={})
