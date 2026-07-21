# Quint (TLAモード) 検証キット

動的安全性検証サブコンポーネント(並行性・打ち切り安全性、
`verification_layer_clarification.md` 2章)の置き場所。

Quintは独立したツール([`@informalsystems/quint`](https://quint-lang.org/))で
あり、Pythonライブラリではないため `requirements.txt` には含まれない。

```bash
npm install -g @informalsystems/quint
quint verify <このケースの>.qnt
```

## このディレクトリにやること(ケースごとに書く)

このケースの①環境層(壁・書き込み順序)と③集約層(打ち切りルール)を
状態遷移として `.qnt` で記述し、以下を確認する仕様を書く。

- 競合状態・デッドロックが起きないか(並行安全性)
- 打ち切り(タイムアウト・最大試行回数超過)発生時も、系が矛盾した状態に
  陥らないか(CLAUDE.md 8章、evaluation_criteria.md #23 打ち切り耐性)

1ケース目(単一プロセス内のシミュレーション)では、この節は
`SMAS_theorymap.md` 1.3節の通り表面化しない可能性が高い。複数プロセス・
実ネットワークをまたぐ実装に移行する際に、実際に仕様を書く。
