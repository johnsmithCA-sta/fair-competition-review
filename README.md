# fair-competition-review

> **政策措施公平竞争审查技能** —— 把一份政策草案，变成一份每条风险都能回溯到法条原文的审查报告和《公平竞争审查表》。

`公平竞争审查` · `政策措施` · `合规审查` | MIT License | Python 3.8+ (stdlib only)

技能本体在 [`skills/fair-competition-review/`](skills/fair-competition-review/)：

| 入口 | 内容 |
|---|---|
| [`SKILL.md`](skills/fair-competition-review/SKILL.md) | 完整工作流、适用与触发、边界与示例 |
| [`README.md`](skills/fair-competition-review/README.md) | 能力概览、对比、快速上手、产出物 |
| `references/` | 四类 66 项审查标准清单、法条溯源映射、审查表模板、版本史 |
| `scripts/` | 正文提取（docx / txt / md）与关键词预筛（零第三方依赖） |

---

## 它做什么

按《公平竞争审查条例》四类标准与《实施办法》66 项细则，对拟出台的政策措施逐条扫描：

1. **判定审查范围** —— 是否属于「涉及经营者经济活动」的政策措施；
2. **逐条扫描定级** —— 每条风险给出条款位置、原文摘录、违反标准编号、风险等级、修改建议；
3. **法条依据溯源** —— 每条规定「法规全称 + 条号 + 原文链接」，附索引汇总表；
4. **判断例外情形** —— 按《条例》第 12 条论证三要件，不把可保留条款判死；
5. **成文输出** —— 审查报告 + 官方通用格式《公平竞争审查表》。

## 快速上手

```bash
cd skills/fair-competition-review

# 1. 提取政策正文
python3 scripts/extract_text.py 政策草案.docx --out policy.txt

# 2. 关键词预筛（定位助手）
python3 scripts/scan_rules.py policy.txt --format md --out prescreen.md

#    只看高危信号：
python3 scripts/scan_rules.py policy.txt --strong-only
```

> ⚠️ 预筛命中不等于违规，**零命中也不等于无风险**——两种情况都要回原文逐条语义核对。

## 边界

- 审查对象是**政策措施**（政府规章、规范性文件草案），不是企业文案、合同或招投标文件；
- 不处理反不正当竞争执法案件、企业自身竞争合规自检、招投标与政府采购文件审查；
- 输出为**审查工作辅助参考**，不构成法律意见，不替代起草单位审查岗与市场监管部门的会审意见。

## License

MIT © 2026 johnsmithCA-sta
