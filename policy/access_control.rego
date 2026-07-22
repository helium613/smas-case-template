package smas.access_control

# 壁(アクセス制御)のポリシー: 各エージェントは自領域(trace.agent_id == writer_id)
# にのみ書き込める。environment.pyのEnvironmentClient.write_traceが元々Python内で
# 直接判定しているルール(writer_id != trace.agent_id ならWallViolation)と、
# 意味的に同一のものを外部ポリシーエンジンの決定として表現する
# (D-32、CLAUDE.md 4章「(横断)アクセス制御」、D-49で実際に組み込んで確認)。

default allow := false

allow if {
	input.writer_id == input.trace_agent_id
}
