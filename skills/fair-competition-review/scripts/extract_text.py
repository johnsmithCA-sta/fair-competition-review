#!/usr/bin/env python3
"""政策文本提取器：docx / txt / md → 纯文本。

纯 Python 标准库实现，无第三方依赖。
docx 通过 zipfile 解析 word/document.xml，按段落还原换行；不保留表格单元格边界，
不涉及图片与样式——公平竞争审查只需要条文文本。

用法:
  python3 extract_text.py 政策草案.docx
  python3 extract_text.py 政策草案.docx --out policy.txt
  python3 extract_text.py 政策草案.docx --out policy.txt --stats
"""
import argparse
import html
import re
import sys
import zipfile

DOCX_PART = "word/document.xml"


def extract_docx(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read(DOCX_PART).decode("utf-8", errors="ignore")
    except zipfile.BadZipFile:
        sys.exit(f"错误：{path} 不是有效的 docx（zip 结构损坏）。\n"
                 f"修：用 Word / WPS 重新另存为 .docx，或先导出为 .txt 再传入。")
    except KeyError:
        sys.exit(f"错误：{path} 里没有 {DOCX_PART}，不是标准 docx。\n"
                 f"修：确认文件确实是 .docx；旧版 .doc 请先另存为 .docx 或 .txt。")
    # 表格单元格与换行/制表符先还原，再剥离所有 XML 标签
    xml = re.sub(r"</w:(p|tr)>", "\n", xml)
    xml = re.sub(r"<w:(br|cr)\s*/>", "\n", xml)
    xml = re.sub(r"<w:tab\s*/>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(xml)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="从 docx / txt / md 提取纯文本，供公平竞争审查使用",
        epilog=("示例:\n"
                "  python3 extract_text.py 政策草案.docx\n"
                "  python3 extract_text.py 政策草案.docx --out policy.txt\n"
                "  python3 extract_text.py 政策草案.docx --out policy.txt --stats"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("file", help="输入文件（.docx / .txt / .md）")
    ap.add_argument("--out", help="输出文件路径（默认打印到标准输出）")
    ap.add_argument("--stats", action="store_true", help="额外打印字符数与段落数")
    args = ap.parse_args()

    lower = args.file.lower()
    try:
        if lower.endswith(".docx"):
            text = extract_docx(args.file)
        elif lower.endswith((".txt", ".md")):
            with open(args.file, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        elif lower.endswith(".doc"):
            sys.exit(f"错误：{args.file} 是旧版 .doc 二进制格式，本脚本不支持。\n"
                     f"修：用 Word / WPS 另存为 .docx 或 .txt 后重试。")
        else:
            sys.exit(f"错误：不支持的文件类型 {args.file}。\n"
                     f"修：支持 .docx / .txt / .md；其他格式请先转换。")
    except FileNotFoundError:
        sys.exit(f"错误：找不到文件 {args.file}\n修：确认路径是否正确、文件名有无空格或括号。")
    except IsADirectoryError:
        sys.exit(f"错误：{args.file} 是目录，不是文件。\n修：传入单个文件路径。")
    except PermissionError:
        sys.exit(f"错误：没有读取 {args.file} 的权限。\n修：检查文件权限，或将文件复制到可读目录。")

    text = clean(text)
    if not text:
        sys.exit(f"错误：{args.file} 提取结果为空。\n"
                 f"修：确认文档正文非空；扫描件 / 图片型 docx 无法提取文字，需先 OCR。")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        msg = f"extract ok -> {args.out}（{len(text)} 字符）"
        if args.stats:
            msg += f"；段落 {len([p for p in text.split(chr(10)) if p.strip()])} 个"
        print(msg)
    else:
        sys.stdout.write(text)
        if args.stats:
            sys.stderr.write(f"\n[stats] {len(text)} 字符，"
                             f"{len([p for p in text.split(chr(10)) if p.strip()])} 段落\n")


if __name__ == "__main__":
    main()
