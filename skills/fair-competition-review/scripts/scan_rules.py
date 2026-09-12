#!/usr/bin/env python3
"""公平竞争审查关键词预筛器。

对纯文本做《公平竞争审查条例》四类标准的关键词/正则预筛，输出疑似命中清单。
**预筛只用于提速定位，命中不等于违规**——每个命中都必须回到上下文语义核对，
「零命中」同样不等于无风险。

用法:
  python3 scan_rules.py policy.txt
  python3 scan_rules.py policy.txt --strong-only --max-hits 100
  python3 scan_rules.py policy.txt --format json --out prescreen.json

规则来源: references/review-standards.md（四类 66 项 + 预筛词库），条文以法规原文为准。
"""
import argparse
import json
import re
import sys

# 结构: 类别 -> 事项(含《实施办法》条号) -> [(模式, 信号强度)]
# 以 "re:" 开头的模式按正则匹配，其余按字面量匹配。
# 信号强度: 强 = 命中即为高度可疑的违规表述; 弱 = 泛词，仅用于定位，需人工过滤。
RULES = {
    "一、市场准入和退出": {
        "第9条 违法设置市场准入审批程序": [
            ("负面清单", "强"), ("准入许可", "强"), ("准入条件", "强"),
            ("审批程序", "强"), ("前置备案", "强"), ("市场禁入", "强"),
            ("re:备案.{0,10}(方可|才能|作为)", "强"),
            ("备案", "弱"), ("认证", "弱"), ("re:目录|名录|计划|规划", "弱"),
        ],
        "第10条 违法设置或授予政府特许经营权": [
            ("特许经营", "强"), ("经营期限", "弱"),
        ],
        "第11条 限定经营、购买、使用特定经营者商品": [
            ("限定经营", "强"), ("限定购买", "强"), ("限定使用", "强"),
            ("指定购买", "强"), ("指定品牌", "强"), ("指定供应商", "强"),
            ("地产品目录", "强"), ("优先采购本地", "强"),
            ("re:本地产品.{0,8}(采购|购买|使用)", "强"),
            ("指定", "弱"), ("备选库", "弱"), ("资格库", "弱"), ("同等条件优先", "弱"),
        ],
        "第12条 不合理或歧视性准入退出条件": [
            ("歧视性准入", "强"), ("退出条件", "强"), ("变更注册地址", "强"),
            ("减少注册资本", "强"), ("本地经营年限", "强"),
            ("经营年限", "弱"), ("属地原则", "弱"), ("区域封锁", "弱"),
        ],
    },
    "二、商品、要素自由流动": {
        "第13条 限制外地商品要素进入、阻碍本地经营者迁出": [
            ("外地", "强"), ("市外", "强"), ("区外", "强"), ("迁出", "强"),
            ("re:承诺.{0,10}不迁", "强"), ("re:不得.{0,8}迁出", "强"),
            ("重复检验", "强"), ("重复认证", "强"),
            ("设卡", "弱"), ("进口商品", "弱"), ("迁入", "弱"),
        ],
        "第14条 排斥限制强制外地经营者本地投资、设分支机构": [
            ("强制在本地投资", "强"), ("属地投资", "强"),
            ("re:在本地(投资|设立|注册).{0,10}(必要条件|前提)", "强"),
            ("分支机构", "弱"),
        ],
        "第15条 排斥限制外地经营者参加本地政府采购、招投标": [
            ("本地政府采购", "强"), ("本地招投标", "强"), ("排斥外地", "强"),
            ("不能接受外地", "强"), ("优先采购本地", "强"), ("本地业绩", "强"),
            ("本地奖项", "强"), ("本地纳税", "强"), ("本地注册", "强"),
            ("re:本地.{0,6}(加分|优先|得分)", "强"),
            ("re:信用等级.{0,10}(产地|注册地)", "强"),
            ("联合体", "弱"), ("本地企业", "弱"), ("同等条件优先", "弱"),
        ],
        "第16条 对外地商品要素设歧视性收费、价格、补贴": [
            ("歧视性收费", "强"), ("歧视性价格", "强"), ("歧视性补贴", "强"),
            ("差别化收费", "弱"),
        ],
        "第17条 资质标准、监管执法歧视": [
            ("资质差异化", "强"), ("监管执法差异", "强"), ("歧视性资质", "强"),
            ("重复执法", "弱"), ("检查频次", "弱"),
        ],
    },
    "三、影响生产经营成本（须先判有无法律、行政法规依据或国务院批准）": {
        "第18条 给予特定经营者税收优惠": [
            ("税收优惠", "强"), ("减免税款", "强"), ("税收减免", "强"),
            ("先征后返", "强"), ("即征即退", "强"), ("列收列支", "强"),
            ("地方留成", "强"),
            ("re:税收.{0,8}(奖励|返还|挂钩)", "强"),
            ("核定征收", "弱"),
        ],
        "第19条 给予特定经营者选择性、差异化财政奖励或补贴": [
            ("财政奖励", "强"), ("财政补助", "强"), ("财政补贴", "强"),
            ("专项资金", "强"), ("扶持资金", "强"), ("奖补", "强"),
            ("一次性奖励", "强"), ("给予奖励", "强"), ("财力贡献", "强"),
            ("一事一议", "强"), ("一企一策", "强"), ("白名单", "强"),
            ("企业库", "强"), ("名录库", "强"), ("重点扶持企业", "强"),
            ("re:按.{0,12}给予.{0,8}奖励", "强"),
            ("re:排名第.{0,3}.{0,6}(奖励|扶持)", "强"),
            ("re:(贡献较大|贡献突出|表现突出)", "强"),
            ("re:注册地?(迁入|迁至|迁移)", "强"),
            ("re:(投资额|营收|销售收入|纳税额).{0,10}(奖励|补助|补贴|奖)", "强"),
            ("补贴", "弱"), ("奖励", "弱"),
        ],
        "第20条 要素获取、行政事业性收费、政府性基金、社保优惠": [
            ("零地价", "强"), ("优惠地价", "强"), ("土地价款", "强"),
            ("租金减免", "强"), ("租金补贴", "强"), ("免费用地", "强"),
            ("行政事业性收费", "强"), ("政府性基金", "强"), ("社会保险费", "强"),
            ("re:(减免|缓征|停征|免征).{0,10}(收费|基金|保险费)", "强"),
        ],
    },
    "四、影响生产经营行为": {
        "第21条 强制或变相强制经营者实施垄断行为": [
            ("垄断协议", "强"), ("协同定价", "强"), ("强制交易", "强"),
            ("re:(价格|成本|产销量|客户信息).{0,8}(披露|公开)", "强"),
            ("行政指导", "弱"), ("备忘录", "弱"), ("敏感信息", "弱"),
        ],
        "第22条 超越权限制定政府指导价、定价、提供优惠价格": [
            ("政府指导价", "强"), ("政府定价", "强"), ("优惠价格", "强"),
            ("定价目录", "弱"),
        ],
        "第23条 违法干预市场调节价价格水平": [
            ("建议价", "强"), ("最高限价", "强"), ("最低限价", "强"),
            ("统一价格", "强"), ("参考价", "强"), ("价格干预", "强"),
            ("干预市场调节价", "强"),
            ("手续费", "弱"), ("折扣", "弱"),
        ],
    },
    "兜底与高危结构信号（第24条）": {
        "其他限制或变相限制竞争": [
            ("排除竞争", "强"), ("限制竞争", "强"), ("滥用行政权力", "强"),
            ("地方保护", "强"), ("行政性垄断", "强"),
            ("re:经(认定|评审|审核|批准)后.{0,10}(给予|享受|奖励|补助)", "强"),
        ],
    },
}

HEADER = "| 位置 | 标准类 | 事项 | 信号 | 命中词 | 上下文摘录 |"
SEP = "|---|---|---|---|---|---|"
MAX_CONTEXT = 160
DEFAULT_MAX_HITS = 200


def _match(text: str, pattern: str) -> bool:
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], text) is not None
        except re.error:
            return pattern[3:] in text
    return pattern in text


def scan(text: str, strong_only: bool = False) -> list:
    """按句切分逐项匹配；同一句命中同一事项只产出一条记录（合并命中词，强信号在前）。"""
    hits = []
    for idx, sent in enumerate(re.split(r"[\n。；;]", text)):
        s = sent.strip()
        if not s:
            continue
        for category, items in RULES.items():
            for item, patterns in items.items():
                matched = []
                for pattern, signal in patterns:
                    if strong_only and signal != "强":
                        continue
                    if _match(s, pattern):
                        matched.append((signal, pattern[3:] if pattern.startswith("re:") else pattern))
                if matched:
                    matched.sort(key=lambda x: (x[0] != "强", x[1]))
                    hits.append({
                        "line": idx + 1,
                        "category": category,
                        "item": item,
                        "signal": "强" if any(m[0] == "强" for m in matched) else "弱",
                        "keywords": [m[1] for m in matched],
                        "context": s[:MAX_CONTEXT],
                    })
    hits.sort(key=lambda h: (h["signal"] != "强", h["line"]))
    return hits


def fmt_md(hits: list, shown: int, total: int) -> str:
    if not hits:
        return ("**预筛结果：关键词库未命中。**\n"
                "这不代表无风险——预筛召回有限，未命中区域仍须逐条语义核对。")
    strong = sum(1 for h in hits if h["signal"] == "强")
    out = [f"**预筛命中 {total} 处（强信号 {strong} 处；仅为预筛，必须逐条语义核对）**\n",
           HEADER, SEP]
    for h in hits[:shown]:
        ctx = h["context"].replace("|", "\\|")
        out.append(f"#{h['line']} | {h['category']} | {h['item']} | {h['signal']} | "
                   f"{'、'.join(h['keywords'])} | {ctx}")
    if total > shown:
        out += ["",
                f"> 已截断：共 {total} 处，仅显示前 {shown} 处。"
                f"取全量：加 `--out prescreen.md`，或用 `--format json`、调大 `--max-hits`。"]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="公平竞争审查关键词预筛（定位助手，不作结论）",
        epilog=("示例:\n"
                "  python3 scan_rules.py policy.txt\n"
                "  python3 scan_rules.py policy.txt --strong-only --max-hits 100\n"
                "  python3 scan_rules.py policy.txt --format json --out prescreen.json"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("file", help="待预筛的政策文本（.txt/.md，或经 extract_text.py 提取后的文本）")
    ap.add_argument("--format", choices=["md", "json"], default="md",
                    help="输出格式：md（默认，人读）/ json（结构化）")
    ap.add_argument("--out", help="输出到文件（默认打印到标准输出）")
    ap.add_argument("--strong-only", action="store_true",
                    help="只报强信号命中，过滤「奖励/补贴/外地」这类泛词噪音")
    ap.add_argument("--max-hits", type=int, default=DEFAULT_MAX_HITS,
                    help=f"md 输出最多展示条数，默认 {DEFAULT_MAX_HITS}；取全量用 --out 或 --format json")
    args = ap.parse_args()

    try:
        with open(args.file, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except FileNotFoundError:
        sys.exit(f"错误：找不到文件 {args.file}\n"
                 f"修：确认路径；docx 请先跑 "
                 f"`python3 extract_text.py \"{args.file}\" --out policy.txt` 再传入。")
    except IsADirectoryError:
        sys.exit(f"错误：{args.file} 是目录，不是文件。\n修：传入单个政策文本文件，或先提取为 .txt。")

    if not text.strip():
        sys.exit(f"错误：{args.file} 内容为空，无法预筛。\n"
                 f"修：确认文本已正确提取（docx 走 extract_text.py）。")

    hits = scan(text, strong_only=args.strong_only)
    total = len(hits)
    if args.format == "json":
        out_text = json.dumps({"file": args.file, "strong_only": args.strong_only,
                               "total": total, "hits": hits},
                              ensure_ascii=False, indent=2)
    else:
        out_text = fmt_md(hits, args.max_hits, total)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_text)
        strong = sum(1 for h in hits if h["signal"] == "强")
        print(f"scan ok -> {args.out}（命中 {total} 处，强信号 {strong} 处）；"
              f"预筛仅为定位，须逐条语义核对")
    else:
        sys.stdout.write(out_text)


if __name__ == "__main__":
    main()
