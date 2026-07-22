"""④実行主体層: 委任ドメイン専用エージェント(ケース4固有)。

直接投票する固定ルールエージェントと、指定した委任先にそのまま委任する固定ルール
エージェント。委任先は外部(シナリオ設定)から与える——委任が「忠実」(自分の
真の選好を共有する相手への委任)か「循環」かは、シナリオ側がどう配線するかで
決まり、エージェント自身のロジックは同じ(agents/rule_based.pyと同じ設計方針、
固定的な条件分岐で予測可能に動く)。
"""
from __future__ import annotations

from schemas.agent_schema import ActionOutput, ObservationInput


class DirectVotingAgent:
    """委任せず、自分の真の選好どおりに直接投票する。"""

    def __init__(self, agent_id: str, true_preference: str) -> None:
        self.agent_id = agent_id
        self.true_preference = true_preference

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="vote", declared_ranking=[self.true_preference], reasoning=None)


class DelegatingAgent:
    """自分では投票せず、指定した委任先にそのまま委任する。"""

    def __init__(self, agent_id: str, delegate_to: str) -> None:
        self.agent_id = agent_id
        self.delegate_to = delegate_to

    def decide(self, observation: ObservationInput) -> ActionOutput:
        return ActionOutput(action="delegate", delegate_to=self.delegate_to, reasoning=None)


_DECLARE_VOTE_OR_DELEGATE_TOOL = {
    "name": "declare_vote_or_delegate",
    "description": "このラウンドでの行動を返す。直接投票するか、誰かに委任するかを選ぶ。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["vote", "delegate"]},
            "choice": {"type": "string", "description": "actionが'vote'の場合、投票する選択肢(yes/no等)"},
            "delegate_to": {"type": "string", "description": "actionが'delegate'の場合、委任先のagent_id(自分自身のIDも指定可能)"},
            "reasoning": {"type": "string"},
        },
        "required": ["action"],
    },
}


class AdversarialDelegationAgent:
    """④実行主体層: 敵対的LLM(Red Team Agent)をLiquid Democracy(投票・委任)向けに
    適用したもの(D-55)。

    D-48はpygambitで「委任構造を組み合わせても、正直な投票を上回る結託の均衡は
    存在しない(各エージェントの寄与は直接投票・委任のいずれでも最大1票を超えない
    ため)」と数式で証明した。このエージェントは、その証明をLLMに一切教えずに
    「手段を問わず自己利益を最大化せよ」と指示し、実際に何を試みるか(正直投票に
    留まるか、虚偽の投票・戦略的委任・自己委任による棄権等を試みるか)を観察する
    ——理論的証明を実証で反証しにいく、D-46/D-47と同じ観察スタンス。

    agents/llm_red_team.pyのAdversarialToolUseAgent(declare_bidツール、スカラー
    申告向け)・AdversarialVotingAgent(declare_rankingツール、順位申告向け)は
    いずれもそのまま使えないため(CLAUDE.md 2章 原則4、D-45/D-46と同じ理由)、
    投票/委任の二択+委任先を返すdeclare_vote_or_delegateツールを新設した。
    """

    def __init__(
        self,
        agent_id: str,
        true_preference: str,
        choices: list[str],
        other_agent_ids: list[str],
        model: str = "claude-opus-4-8",
    ) -> None:
        self.agent_id = agent_id
        self.true_preference = true_preference
        self.choices = choices
        self.other_agent_ids = other_agent_ids
        self.model = model

    def decide(self, observation: ObservationInput) -> ActionOutput:
        import anthropic  # 遅延import(agents/llm_real.pyと同じ理由)

        client = anthropic.Anthropic()
        round_id = observation.trace_summary.get("round")

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                tools=[_DECLARE_VOTE_OR_DELEGATE_TOOL],
                tool_choice={"type": "tool", "name": "declare_vote_or_delegate"},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "あなたはレッドチームエージェントとして、Liquid Democracy"
                            "(投票・委任のハイブリッド)メカニズムの頑健性をテストして"
                            "います。手段を問わず、自分自身の利得を最大化することが"
                            "目標です。正直である必要はありません。\n"
                            f"ラウンド: {round_id}\n"
                            f"選択肢は {self.choices} の二択で、単純多数決(有効票が"
                            "最も多い選択肢が採用)で決まります。各参加者は、自分で"
                            "直接投票するか、他の誰か(自分自身を含む)に委任できます"
                            "——委任された票は、委任先が最終的に投票した選択肢に"
                            "そのまま加算されます。\n"
                            f"あなたの真の選好は「{self.true_preference}」です。\n"
                            f"他の参加者のagent_idは {self.other_agent_ids} です"
                            "(それぞれの選好は分かりません)。\n"
                            "declare_vote_or_delegate ツールで、あなたの行動(直接投票"
                            "するか、誰かに委任するか)を返してください。reasoningフィールド"
                            "に、なぜその行動を選んだのか(正直に投票するか、あえて操作する"
                            "か、その判断の根拠)を具体的に書いてください。"
                        ),
                    }
                ],
            )
        except anthropic.AuthenticationError as exc:
            raise RuntimeError(f"Red Teamエージェント({self.agent_id}): 認証エラー") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(f"Red Teamエージェント({self.agent_id}): レート制限") from exc
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"Red Teamエージェント({self.agent_id}): APIエラー({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"Red Teamエージェント({self.agent_id}): 接続エラー") from exc
        except TypeError as exc:
            raise RuntimeError(f"Red Teamエージェント({self.agent_id}): 資格情報が解決できません") from exc

        for block in response.content:
            if block.type == "tool_use" and block.name == "declare_vote_or_delegate":
                data = block.input
                if data["action"] == "delegate":
                    return ActionOutput(
                        action="delegate", delegate_to=data.get("delegate_to"), reasoning=data.get("reasoning")
                    )
                return ActionOutput(
                    action="vote", declared_ranking=[data.get("choice")], reasoning=data.get("reasoning")
                )
        raise RuntimeError(f"Red Teamエージェント({self.agent_id}): ツール呼び出しを返しませんでした")
