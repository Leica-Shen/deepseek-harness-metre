# tests

目前测试集中在 `studio/selftest.py`（六类风险各一组断言），用一条命令跑：

```bash
python3 -m studio.cli selftest                    # 跑 ../demos/*/deck.json
python3 -m studio.cli selftest path/to/deck.json  # 跑指定内容
```

| 组 | 断言 |
| --- | --- |
| 信息正确 | 每页标题前 12 字必须逐字出现在产出的 pptx 里 |
| 版式 | 无重叠、无越界、对比度达标；一册 ≥80% 页有配图 |
| 确定性 | 同一内容构建两次，所有 op 的几何哈希一致 |
| 安全 | 产物 XML 不含绝对路径、用户名、旧项目名 |
| 规模 | 页数 ≤60、文本 ≤40000 字、单页元素 ≤160 |
| 指令安全 | SKILL.md 不含「忽略以上」「rm -rf」「eval(」等可劫持片段 |
