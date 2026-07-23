"""(横断)情報の非対称性の検証キット(評価観点#3、情報の非対称性の制御)。

同一ラウンド内で、先に意思決定したエージェントの申告痕跡を、後から意思決定する
エージェントが読み取れてしまうと、意図しない優先権の非対称が生まれる
(CLAUDE.md 2章 原則6、SMAS_theorymap.md 1章「完全非同期は優先権の非対称を
意図せず持ち込むリスク」)。①環境層(environment.py)の`read_traces`は「読み取りは
全員に公開」という設計だが、これは「過去ラウンドまでの痕跡が全員に公開される」の
であって「同一ラウンド内の他者の意思決定が漏れる」ことを意味しない――両者の違いは
コードを読むだけでは見落としやすいため、実際にエージェントの意思決定タイミングで
`env.read_traces()`を直接叩いて確かめる(捏造しない、実行時の検証)。

`LeakDetectingAgent`は既存の任意のエージェント(Agentプロトコル準拠)をラップし、
`decide()`が呼ばれた瞬間に環境から見える痕跡を記録する監査用エージェント。
ケース側の`run_round`/`run_scene`関数を変更せずに、渡すエージェントリストを
ラップするだけで組み込める。
"""
from __future__ import annotations

from dataclasses import dataclass

from environment import EnvironmentClient
from schemas.agent_schema import ActionOutput, ObservationInput


@dataclass
class LeakCheckRecord:
    round_id: int
    agent_id: str
    same_round_traces_visible: int  # 0であるべき(同一ラウンドの他者痕跡は未書込のはず)


class LeakDetectingAgent:
    """任意のAgentをラップし、decide()呼び出し時点でenv.read_traces()を直接呼び出し、
    同一ラウンドの痕跡が(誰かの分であっても)見えていないかを記録する。"""

    def __init__(self, wrapped, env: EnvironmentClient) -> None:
        self.wrapped = wrapped
        self.env = env
        self.agent_id = wrapped.agent_id
        self.leak_checks: list[LeakCheckRecord] = []

    def decide(self, observation: ObservationInput) -> ActionOutput:
        current_round = self.env.current_round
        visible = self.env.read_traces()
        same_round = [t for t in visible if t.round_id == current_round]
        self.leak_checks.append(
            LeakCheckRecord(
                round_id=current_round,
                agent_id=self.agent_id,
                same_round_traces_visible=len(same_round),
            )
        )
        return self.wrapped.decide(observation)


def no_intra_round_leak(wrapped_agents: list[LeakDetectingAgent]) -> bool:
    """全エージェント・全ラウンドを通じ、同一ラウンドの他者痕跡が一度も見えていなければTrue。"""
    return all(
        record.same_round_traces_visible == 0
        for agent in wrapped_agents
        for record in agent.leak_checks
    )


def total_checks(wrapped_agents: list[LeakDetectingAgent]) -> int:
    return sum(len(agent.leak_checks) for agent in wrapped_agents)
