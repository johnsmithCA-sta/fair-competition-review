#!/usr/bin/env python3
"""审查报告 / 审查表 → .docx 导出器。

纯 Python 标准库实现，无第三方依赖。把本技能产出的 Markdown（审查报告、审查表）
转成可直接进入发文流程的 .docx：支持标题、正文、有序/无序列表、管道表格、引用、
代码块、分隔线，以及行内 **加粗** / `等宽` / [链接](url)。

用法:
  python3 export_docx.py 公平竞争审查报告_XX办法.md
  python3 export_docx.py 公平竞争审查表_XX办法.md --out 审查表_XX办法.docx
  python3 export_docx.py 报告.md --check          # 只做转换自检，不写文件
"""
import argparse
import html
import os
import re
import sys
import zipfile

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

# 字号以半磅为单位：24 = 小四(12pt)，28 = 四号(14pt)，36 = 小二(18pt)
BODY_SZ, H1_SZ, H2_SZ, H3_SZ = 24, 36, 28, 24
BODY_FONT, ASCII_FONT = "宋体", "Times New Roman"


# ---------------------------------------------------------------- 行内解析

def esc(t: str) -> str:
    return html.escape(t, quote=False)


def inline_runs(text: str):
    """把一段文本拆成 [(文字, 加粗, 等宽)]，处理 **粗**、`码`、[文字](链接)。"""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = text.replace("\\|", "|")
    runs, pos = [], 0
    pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    for m in pattern.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False, False))
        if m.group(1) is not None:
            runs.append((m.group(1), True, False))
        else:
            runs.append((m.group(2), False, True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False, False))
    return [r for r in runs if r[0] != ""] or [("", False, False)]


def run_xml(text: str, bold: bool = False, mono: bool = False,
            sz: int = BODY_SZ, color: str = None) -> str:
    rpr = [f'<w:rFonts w:ascii="{ASCII_FONT}" w:hAnsi="{ASCII_FONT}" '
           f'w:eastAsia="{"Consolas" if mono else BODY_FONT}"/>']
    if bold:
        rpr.append("<w:b/>")
    if color:
        rpr.append(f'<w:color w:val="{color}"/>')
    rpr.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
    return (f'<w:r><w:rPr>{"".join(rpr)}</w:rPr>'
            f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r>')


def para(runs: str, align: str | None = None, indent: int = 0,
         space_before: int = 0, space_after: int = 60) -> str:
    ppr = []
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    if indent:
        ppr.append(f'<w:ind w:left="{indent}"/>')
    ppr.append(f'<w:spacing w:before="{space_before}" w:after="{space_after}"/>')
    return f'<w:p><w:pPr>{"".join(ppr)}</w:pPr>{runs}</w:p>'


# ---------------------------------------------------------------- 表格

BORDERS = ("<w:tblBorders>"
           + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
           + "</w:tblBorders>")

PAGE_TEXT_TWIPS = 9638          # A4 宽 11906 - 左右页边距 1134×2
COL_MIN, COL_MAX = 10, 46       # 列宽（显示宽度）上下限，防止单列过窄或吃掉全表


def _disp_width(s: str) -> int:
    """显示宽度：CJK 全角按 2，其余按 1——用于按内容分配列宽。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def col_widths(rows):
    """按各列最长内容的比例分配页宽，避免一律等宽导致长文本被挤压。"""
    ncol = len(rows[0])
    weights = [max(_disp_width(r[c]) for r in rows) for c in range(ncol)]
    weights = [min(max(w, COL_MIN), COL_MAX) for w in weights]
    total = sum(weights)
    return [int(PAGE_TEXT_TWIPS * w / total) for w in weights]


def cell_xml(cells, header: bool, widths) -> str:
    tcs = []
    for c, w in zip(cells, widths):
        runs = "".join(run_xml(t, bold=header or b, mono=m, sz=BODY_SZ - 2)
                       for t, b, m in inline_runs(c))
        tcs.append(f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
                   f'<w:p><w:pPr><w:spacing w:before="20" w:after="20"/></w:pPr>{runs}</w:p></w:tc>')
    return f'<w:tr>{"".join(tcs)}</w:tr>'


def table_xml(rows) -> str:
    widths = col_widths(rows)
    body = []
    for i, r in enumerate(rows):
        tr = cell_xml(r, i == 0, widths)
        if i == 0:  # 表头跨页重复
            tr = tr.replace("<w:tr>", "<w:tr><w:trPr><w:tblHeader/></w:trPr>", 1)
        body.append(tr)
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
            f'<w:tblLayout w:type="fixed"/>{BORDERS}</w:tblPr>'
            f'{"".join(body)}</w:tbl>' + para(""))


# ---------------------------------------------------------------- Markdown → 块

def parse_md(text: str):
    lines = text.replace("\r\n", "\n").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        if not s:
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"-{3,}|\*{3,}", s):
            blocks.append(("hr", None))
            i += 1
            continue

        # 标题
        m = re.match(r"(#{1,4})\s+(.*)$", s)
        if m:
            blocks.append(("h", (len(m.group(1)), m.group(2).strip())))
            i += 1
            continue

        # 表格
        if s.startswith("|") and i + 1 < len(lines) and \
           re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip()):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw = lines[i].strip()
                if not re.fullmatch(r"\|[\s:|-]+\|", raw):
                    # 按未转义的竖线切分（单元格内的 \| 是内容，不是分隔符）
                    cells = [c.strip() for c in re.split(r"(?<!\\)\|", raw.strip("|"))]
                    rows.append(cells)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                blocks.append(("table", rows))
            continue

        # 引用
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(("quote", " ".join(x for x in buf if x)))
            continue

        # 代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", buf))
            continue

        # 列表
        m = re.match(r"([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            ordered = m.group(1)[0].isdigit()
            items = []
            while i < len(lines):
                mm = re.match(r"([-*+]|\d+[.)])\s+(.*)$", lines[i].strip())
                if not mm or mm.group(1)[0].isdigit() != ordered:
                    break
                items.append(mm.group(2).strip())
                i += 1
            blocks.append(("ol" if ordered else "ul", items))
            continue

        # 段落（合并到下一个空行）
        buf = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and \
                not re.match(r"^(#{1,4}\s|\||>|```|[-*+]\s|\d+[.)]\s)", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


# ---------------------------------------------------------------- 块 → document.xml

def blocks_to_body(blocks) -> str:
    out = []
    for kind, val in blocks:
        if kind == "h":
            lvl, txt = val
            sz = {1: H1_SZ, 2: H2_SZ, 3: H3_SZ}.get(lvl, H3_SZ)
            out.append(para(run_xml(txt, bold=True, sz=sz),
                            align="center" if lvl == 1 else None,
                            space_before=200 if lvl > 1 else 0, space_after=120))
        elif kind == "p":
            out.append(para("".join(run_xml(t, b, m) for t, b, m in inline_runs(val))))
        elif kind == "ul":
            for it in val:
                runs = "".join(run_xml(t, b, m) for t, b, m in inline_runs(it))
                out.append(para(run_xml("• ") + runs, indent=240, space_after=40))
        elif kind == "ol":
            for n, it in enumerate(val, 1):
                runs = "".join(run_xml(t, b, m) for t, b, m in inline_runs(it))
                out.append(para(run_xml(f"{n}. ") + runs, indent=240, space_after=40))
        elif kind == "table":
            out.append(table_xml(val))
        elif kind == "quote":
            out.append(para(run_xml(val, sz=BODY_SZ - 2, color="595959"), indent=240))
        elif kind == "code":
            for ln in val:
                out.append(para(run_xml(ln or " ", mono=True, sz=BODY_SZ - 4),
                                indent=240, space_after=0))
            out.append(para(""))
        elif kind == "hr":
            out.append(para(run_xml("─" * 30, sz=BODY_SZ - 4, color="A6A6A6"),
                            align="center", space_after=80))
    return "".join(out)


SECT_PR = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1440" w:right="1134" w:bottom="1440" w:left="1134" '
           'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')


def build_docx(md_text: str) -> str:
    body = blocks_to_body(parse_md(md_text))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:document {W}><w:body>{body}{SECT_PR}</w:body></w:document>')


def self_check(path: str) -> str:
    """重开 zip 做结构自检：部件齐、document.xml 可解析、段落数 > 0。"""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        missing = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} - names
        if missing:
            sys.exit(f"错误：生成包缺少部件 {sorted(missing)}。\n修：这是脚本缺陷，请连同输入文件一并反馈。")
        doc = z.read("word/document.xml").decode("utf-8")
    paras = doc.count("<w:p>") + doc.count("<w:p ")
    if paras == 0:
        sys.exit("错误：生成的 docx 正文为空（0 段落）。\n修：确认输入 Markdown 有正文内容。")
    if not doc.rstrip().endswith("</w:document>"):
        sys.exit("错误：document.xml 结构不完整。\n修：这是脚本缺陷，请反馈。")
    return f"{len(names)} 部件 / {paras} 段落 / {doc.count('<w:tbl>')} 表格"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="审查报告 / 审查表 Markdown → .docx（纯标准库，零依赖）",
        epilog=("示例:\n"
                "  python3 export_docx.py 公平竞争审查报告_XX办法.md\n"
                "  python3 export_docx.py 公平竞争审查表_XX办法.md --out 审查表.docx\n"
                "  python3 export_docx.py 报告.md --check"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("file", help="输入的 Markdown 文件（审查报告或审查表）")
    ap.add_argument("--out", help="输出 .docx 路径（默认与输入同名同目录）")
    ap.add_argument("--check", action="store_true", help="只做转换自检，不写文件")
    args = ap.parse_args()

    if args.file.lower().endswith((".docx", ".doc")):
        sys.exit(f"错误：{args.file} 已是 Word 文件，无需转换。\n修：请传入 .md 源文件。")
    try:
        with open(args.file, encoding="utf-8", errors="ignore") as f:
            md = f.read()
    except FileNotFoundError:
        sys.exit(f"错误：找不到文件 {args.file}\n修：确认路径；文件需为 .md（审查报告或审查表）。")
    except IsADirectoryError:
        sys.exit(f"错误：{args.file} 是目录。\n修：传入单个 .md 文件。")

    if not md.strip():
        sys.exit(f"错误：{args.file} 内容为空。\n修：确认报告已生成且非空。")

    doc = build_docx(md)
    out = args.out or os.path.splitext(args.file)[0] + ".docx"

    if args.check:
        tmp = out + ".check"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", RELS)
            z.writestr("word/document.xml", doc)
        detail = self_check(tmp)
        os.remove(tmp)
        print(f"check ok（未写文件）｜{detail}")
        return

    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", RELS)
            z.writestr("word/document.xml", doc)
    except PermissionError:
        sys.exit(f"错误：没有写入 {out} 的权限。\n修：指定 --out 到可写目录，或先关闭已打开的同名文档。")

    print(f"export ok -> {out}（{self_check(out)}）")


if __name__ == "__main__":
    main()
