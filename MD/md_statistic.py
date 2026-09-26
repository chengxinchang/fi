"""
Markdown 文件统计工具

统计内容：
    - 各级标题数量（# ~ ######）
    - 文字总数（中英文分开统计）
    - 行数、段落数、空行数
    - 代码块数量、代码行数
    - 链接、图片、表格数量
    - 引用块、列表项数量

依赖：无（纯标准库）

用法：
    # 统计单个文件
    python md_stats.py input.md

    # 统计多个文件
    python md_stats.py a.md b.md c.md

    # 统计目录下所有 MD 文件
    python md_stats.py ./md_files/

    # 递归统计
    python md_stats.py ./md_files/ --recursive

    # 输出到文件
    python md_stats.py input.md -o stats.txt

    # JSON 格式输出
    python md_stats.py input.md --json
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


# ============ 颜色 ============
class Color:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def enable_windows_ansi():
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            for attr in dir(Color):
                if not attr.startswith('_'):
                    setattr(Color, attr, '')


# ============ 正则 ============
# 标题：# 开头，后面至少一个空格
RE_HEADING = re.compile(r'^(#{1,6})\s+(.*)$')

# 代码块围栏
RE_CODE_FENCE = re.compile(r'^```')

# 行内代码
RE_INLINE_CODE = re.compile(r'`[^`]+`')

# 链接 [text](url)
RE_LINK = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')

# 图片 ![alt](url)
RE_IMAGE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

# 引用块
RE_QUOTE = re.compile(r'^\s*>\s?')

# 无序列表
RE_UL = re.compile(r'^\s*[-*+]\s+')

# 有序列表
RE_OL = re.compile(r'^\s*\d+\.\s+')

# 水平线
RE_HR = re.compile(r'^\s*([-*_])\s*(\1\s*){2,}$')

# 表格分隔行
RE_TABLE_SEP = re.compile(r'^\s*\|?[\s:]*-{3,}[\s:]*\|')

# 中文字符
RE_CHINESE = re.compile(r'[\u4e00-\u9fff]')

# 英文字母
RE_ENGLISH = re.compile(r'[a-zA-Z]')

# 数字
RE_DIGIT = re.compile(r'\d')

# HTML 标签
RE_HTML_TAG = re.compile(r'<[^>]+>')


# ============ 统计函数 ============
def count_stats(content: str) -> dict:
    """
    统计 Markdown 内容。

    :param content: MD 文本
    :return: 统计信息字典
    """
    lines = content.split('\n')

    stats = {
        # 行相关
        'total_lines': len(lines),
        'empty_lines': 0,
        'content_lines': 0,

        # 标题
        'headings': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0},
        'total_headings': 0,

        # 文字
        'total_chars': 0,          # 总字符数（含空格）
        'chars_no_space': 0,       # 不含空格
        'chinese_chars': 0,        # 中文字符
        'english_chars': 0,        # 英文字母
        'digit_chars': 0,          # 数字
        'punctuation_chars': 0,    # 标点

        # 词汇
        'chinese_words': 0,        # 中文词（按字符估算）
        'english_words': 0,        # 英文单词

        # 结构
        'code_blocks': 0,
        'code_lines': 0,
        'inline_codes': 0,
        'links': 0,
        'images': 0,
        'quotes': 0,
        'ul_items': 0,
        'ol_items': 0,
        'tables': 0,
        'horizontal_rules': 0,
        'paragraphs': 0,

        # 代码块内文字
        'code_chars': 0,
        'text_chars': 0,           # 非代码块的字符数
    }

    in_code_block = False
    code_fence_count = 0
    prev_was_empty = True  # 用于段落统计

    for line in lines:
        stripped = line.strip()

        # ---- 空行 ----
        if not stripped:
            stats['empty_lines'] += 1
            prev_was_empty = True
            continue

        stats['content_lines'] += 1

        # ---- 代码块 ----
        if RE_CODE_FENCE.match(stripped):
            code_fence_count += 1
            if code_fence_count % 2 == 1:
                in_code_block = True
                stats['code_blocks'] += 1
            else:
                in_code_block = False
            stats['code_lines'] += 1
            prev_was_empty = False
            continue

        if in_code_block:
            stats['code_lines'] += 1
            stats['code_chars'] += len(line)
            prev_was_empty = False
            continue

        # ---- 标题 ----
        m = RE_HEADING.match(stripped)
        if m:
            level = len(m.group(1))
            stats['headings'][level] += 1
            stats['total_headings'] += 1
            prev_was_empty = False
            continue

        # ---- 水平线 ----
        if RE_HR.match(stripped):
            stats['horizontal_rules'] += 1
            prev_was_empty = False
            continue

        # ---- 引用块 ----
        if RE_QUOTE.match(line):
            stats['quotes'] += 1

        # ---- 列表 ----
        if RE_UL.match(line):
            stats['ul_items'] += 1
        elif RE_OL.match(line):
            stats['ol_items'] += 1

        # ---- 表格 ----
        if RE_TABLE_SEP.match(stripped):
            stats['tables'] += 1

        # ---- 段落（连续非空行算一段，空行分隔）----
        if prev_was_empty:
            stats['paragraphs'] += 1
        prev_was_empty = False

        # ---- 行内元素 ----
        stats['inline_codes'] += len(RE_INLINE_CODE.findall(line))
        stats['images'] += len(RE_IMAGE.findall(line))

        # 链接：先算所有，再减去图片（图片也是链接语法）
        all_links = RE_LINK.findall(line)
        image_count = len(RE_IMAGE.findall(line))
        stats['links'] += max(0, len(all_links) - image_count)

    # ===== 文字统计 =====
    # 去掉代码块后统计纯文字
    text_only = _remove_code_blocks(content)
    text_only = RE_HTML_TAG.sub('', text_only)

    stats['total_chars'] = len(text_only)
    stats['chars_no_space'] = len(re.sub(r'\s', '', text_only))
    stats['chinese_chars'] = len(RE_CHINESE.findall(text_only))
    stats['english_chars'] = len(RE_ENGLISH.findall(text_only))
    stats['digit_chars'] = len(RE_DIGIT.findall(text_only))

    # 标点：总字符 - 中文 - 英文 - 数字 - 空白
    stats['punctuation_chars'] = (
        stats['total_chars']
        - stats['chinese_chars']
        - stats['english_chars']
        - stats['digit_chars']
        - len(re.findall(r'\s', text_only))
    )

    # 中文词：按 2 个字符估算
    stats['chinese_words'] = stats['chinese_chars'] // 2

    # 英文单词：按空格/标点分割
    english_words = re.findall(r"[a-zA-Z]+(?:'[a-zA-Z]+)?", text_only)
    stats['english_words'] = len(english_words)

    # 非代码块文字
    stats['text_chars'] = stats['total_chars']

    return stats


def _remove_code_blocks(content: str) -> str:
    """去掉代码块内容，保留其他部分"""
    lines = content.split('\n')
    result = []
    in_code = False

    for line in lines:
        if RE_CODE_FENCE.match(line.strip()):
            in_code = not in_code
            continue
        if not in_code:
            result.append(line)

    return '\n'.join(result)


def count_chinese_words(text: str) -> int:
    """
    更准确的中文词数估算。
    简单按 2 字一词估算（不调用分词库）。
    """
    chinese_chars = len(RE_CHINESE.findall(text))
    return chinese_chars // 2


# ============ 格式化输出 ============
def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ['KB', 'MB', 'GB']:
        size_bytes /= 1024
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
    return f"{size_bytes:.2f} TB"


def print_stats(stats: dict, file_path: str, file_size: int):
    """打印统计结果"""
    print(f"\n{Color.CYAN}{'='*70}{Color.RESET}")
    print(f"{Color.BOLD}📄 {file_path}{Color.RESET}")
    print(f"{Color.CYAN}{'='*70}{Color.RESET}")

    # ---- 文件信息 ----
    print(f"\n{Color.BOLD}📁 文件信息{Color.RESET}")
    print(f"   文件大小:     {format_size(file_size)}")
    print(f"   总行数:       {stats['total_lines']:,}")
    print(f"   非空行:       {stats['content_lines']:,}")
    print(f"   空行:         {stats['empty_lines']:,}")
    print(f"   段落数:       {stats['paragraphs']:,}")

    # ---- 标题 ----
    print(f"\n{Color.BOLD}📑 标题统计{Color.RESET}")
    print(f"   总标题数:     {Color.GREEN}{stats['total_headings']:,}{Color.RESET}")

    heading_names = {
        1: '一级标题 (#)',
        2: '二级标题 (##)',
        3: '三级标题 (###)',
        4: '四级标题 (####)',
        5: '五级标题 (#####)',
        6: '六级标题 (######)',
    }

    for level in range(1, 7):
        count = stats['headings'][level]
        if count > 0 or level <= 3:
            # 用不同颜色高亮一级、二级
            if level == 1:
                color = Color.MAGENTA
            elif level == 2:
                color = Color.CYAN
            elif level == 3:
                color = Color.BLUE
            else:
                color = Color.DIM

            print(f"   {heading_names[level]:<20} "
                  f"{color}{count:>6,}{Color.RESET}")

    # ---- 文字 ----
    print(f"\n{Color.BOLD}📝 文字统计{Color.RESET}")
    print(f"   总字符数:     {stats['total_chars']:,} "
          f"{Color.DIM}(不含代码块){Color.RESET}")
    print(f"   不含空格:     {stats['chars_no_space']:,}")
    print(f"   中文字符:     {Color.GREEN}{stats['chinese_chars']:,}{Color.RESET}")
    print(f"   英文字母:     {stats['english_chars']:,}")
    print(f"   数字:         {stats['digit_chars']:,}")
    print(f"   标点/其他:    {stats['punctuation_chars']:,}")

    print(f"\n   {Color.DIM}词汇估算（近似值）:{Color.RESET}")
    print(f"   中文词:       ~{stats['chinese_words']:,} "
          f"{Color.DIM}(按 2 字/词){Color.RESET}")
    print(f"   英文单词:     {stats['english_words']:,}")

    # ---- 结构 ----
    print(f"\n{Color.BOLD}🔧 结构统计{Color.RESET}")
    print(f"   代码块:       {stats['code_blocks']:,}")
    print(f"   代码行数:     {stats['code_lines']:,}")
    print(f"   行内代码:     {stats['inline_codes']:,}")
    print(f"   链接:         {stats['links']:,}")
    print(f"   图片:         {stats['images']:,}")
    print(f"   引用块:       {stats['quotes']:,}")
    print(f"   无序列表项:   {stats['ul_items']:,}")
    print(f"   有序列表项:   {stats['ol_items']:,}")
    print(f"   表格:         {stats['tables']:,}")
    print(f"   水平线:       {stats['horizontal_rules']:,}")


def print_summary(all_stats: List[dict]):
    """打印多个文件的汇总"""
    if len(all_stats) <= 1:
        return

    print(f"\n{Color.CYAN}{'='*70}{Color.RESET}")
    print(f"{Color.BOLD}📊 汇总统计（{len(all_stats)} 个文件）{Color.RESET}")
    print(f"{Color.CYAN}{'='*70}{Color.RESET}")

    total_files = len(all_stats)
    total_size = sum(s['file_size'] for s in all_stats)
    total_lines = sum(s['stats']['total_lines'] for s in all_stats)
    total_chars = sum(s['stats']['total_chars'] for s in all_stats)
    total_chinese = sum(s['stats']['chinese_chars'] for s in all_stats)
    total_english = sum(s['stats']['english_chars'] for s in all_stats)
    total_h1 = sum(s['stats']['headings'][1] for s in all_stats)
    total_h2 = sum(s['stats']['headings'][2] for s in all_stats)
    total_h3 = sum(s['stats']['headings'][3] for s in all_stats)
    total_headings = sum(s['stats']['total_headings'] for s in all_stats)
    total_code_blocks = sum(s['stats']['code_blocks'] for s in all_stats)
    total_links = sum(s['stats']['links'] for s in all_stats)
    total_images = sum(s['stats']['images'] for s in all_stats)

    print(f"\n   文件数:       {total_files:,}")
    print(f"   总大小:       {format_size(total_size)}")
    print(f"   总行数:       {total_lines:,}")
    print(f"   总字符数:     {total_chars:,}")
    print(f"   中文字符:     {total_chinese:,}")
    print(f"   英文字母:     {total_english:,}")

    print(f"\n   标题总数:     {total_headings:,}")
    print(f"   {Color.MAGENTA}一级标题:     {total_h1:,}{Color.RESET}")
    print(f"   {Color.CYAN}二级标题:     {total_h2:,}{Color.RESET}")
    print(f"   {Color.BLUE}三级标题:     {total_h3:,}{Color.RESET}")

    print(f"\n   代码块:       {total_code_blocks:,}")
    print(f"   链接:         {total_links:,}")
    print(f"   图片:         {total_images:,}")


# ============ 文件处理 ============
def analyze_file(file_path: Path) -> Optional[dict]:
    """分析单个 MD 文件"""
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding='gbk')
        except Exception as e:
            print(f"{Color.RED}❌ 无法读取 {file_path}: {e}{Color.RESET}")
            return None
    except Exception as e:
        print(f"{Color.RED}❌ 无法读取 {file_path}: {e}{Color.RESET}")
        return None

    stats = count_stats(content)
    file_size = file_path.stat().st_size

    return {
        'file': str(file_path),
        'file_name': file_path.name,
        'file_size': file_size,
        'stats': stats,
    }


def collect_md_files(path: str, recursive: bool = False) -> List[Path]:
    """收集 MD 文件"""
    p = Path(path).resolve()

    if p.is_file():
        if p.suffix.lower() in ('.md', '.markdown', '.mdown', '.mkd'):
            return [p]
        else:
            print(f"{Color.RED}❌ 不是 Markdown 文件: {p}{Color.RESET}")
            return []

    if p.is_dir():
        if recursive:
            files = list(p.rglob('*.md')) + list(p.rglob('*.markdown'))
        else:
            files = list(p.glob('*.md')) + list(p.glob('*.markdown'))
        return sorted(set(files))

    print(f"{Color.RED}❌ 路径不存在: {p}{Color.RESET}")
    return []


# ============ 输出到文件 ============
def write_text_report(results: List[dict], output_path: str):
    """把统计结果写入文本文件"""
    lines = []

    lines.append("=" * 70)
    lines.append("Markdown 文件统计报告")
    lines.append("=" * 70)
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"文件数量: {len(results)}")
    lines.append("")

    for r in results:
        stats = r['stats']
        lines.append("-" * 70)
        lines.append(f"文件: {r['file']}")
        lines.append(f"大小: {format_size(r['file_size'])}")
        lines.append("-" * 70)
        lines.append("")

        lines.append("[文件信息]")
        lines.append(f"  总行数:     {stats['total_lines']:,}")
        lines.append(f"  非空行:     {stats['content_lines']:,}")
        lines.append(f"  空行:       {stats['empty_lines']:,}")
        lines.append(f"  段落数:     {stats['paragraphs']:,}")
        lines.append("")

        lines.append("[标题统计]")
        lines.append(f"  总标题数:   {stats['total_headings']:,}")
        for level in range(1, 7):
            count = stats['headings'][level]
            prefix = '#' * level
            lines.append(f"  {prefix:<8}    {count:>6,}")
        lines.append("")

        lines.append("[文字统计]")
        lines.append(f"  总字符数:   {stats['total_chars']:,}")
        lines.append(f"  中文字符:   {stats['chinese_chars']:,}")
        lines.append(f"  英文字母:   {stats['english_chars']:,}")
        lines.append(f"  数字:       {stats['digit_chars']:,}")
        lines.append(f"  中文词:     ~{stats['chinese_words']:,}")
        lines.append(f"  英文单词:   {stats['english_words']:,}")
        lines.append("")

        lines.append("[结构统计]")
        lines.append(f"  代码块:     {stats['code_blocks']:,}")
        lines.append(f"  代码行数:   {stats['code_lines']:,}")
        lines.append(f"  链接:       {stats['links']:,}")
        lines.append(f"  图片:       {stats['images']:,}")
        lines.append(f"  引用块:     {stats['quotes']:,}")
        lines.append(f"  表格:       {stats['tables']:,}")
        lines.append("")

    # 汇总
    if len(results) > 1:
        lines.append("=" * 70)
        lines.append("汇总")
        lines.append("=" * 70)

        total_size = sum(r['file_size'] for r in results)
        total_lines = sum(r['stats']['total_lines'] for r in results)
        total_chars = sum(r['stats']['total_chars'] for r in results)
        total_chinese = sum(r['stats']['chinese_chars'] for r in results)
        total_h1 = sum(r['stats']['headings'][1] for r in results)
        total_h2 = sum(r['stats']['headings'][2] for r in results)
        total_headings = sum(r['stats']['total_headings'] for r in results)

        lines.append(f"  文件数:     {len(results):,}")
        lines.append(f"  总大小:     {format_size(total_size)}")
        lines.append(f"  总行数:     {total_lines:,}")
        lines.append(f"  总字符数:   {total_chars:,}")
        lines.append(f"  中文字符:   {total_chinese:,}")
        lines.append(f"  标题总数:   {total_headings:,}")
        lines.append(f"  一级标题:   {total_h1:,}")
        lines.append(f"  二级标题:   {total_h2:,}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\n{Color.GREEN}✅ 报告已保存: {output_path}{Color.RESET}")


# ============ 命令行 ============
def main():
    enable_windows_ansi()

    parser = argparse.ArgumentParser(
        description='Markdown 文件统计工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{Color.BOLD}统计内容:{Color.RESET}

  - 各级标题数量（# ~ ######）
  - 中英文字符数、词汇估算
  - 行数、段落数、空行数
  - 代码块、链接、图片、表格、列表等

{Color.BOLD}示例:{Color.RESET}

  {Color.CYAN}# 统计单个文件{Color.RESET}
  python md_stats.py input.md

  {Color.CYAN}# 统计多个文件{Color.RESET}
  python md_stats.py a.md b.md c.md

  {Color.CYAN}# 统计目录{Color.RESET}
  python md_stats.py ./md_files/

  {Color.CYAN}# 递归统计{Color.RESET}
  python md_stats.py ./md_files/ --recursive

  {Color.CYAN}# 输出到文件{Color.RESET}
  python md_stats.py input.md -o stats.txt

  {Color.CYAN}# JSON 格式{Color.RESET}
  python md_stats.py input.md --json

  {Color.CYAN}# JSON 保存到文件{Color.RESET}
  python md_stats.py input.md --json -o stats.json
        """
    )

    parser.add_argument('paths', nargs='+',
                        help='MD 文件或目录（可多个）')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='递归扫描目录')
    parser.add_argument('-o', '--output', default=None,
                        help='输出文件路径')
    parser.add_argument('--json', action='store_true',
                        help='以 JSON 格式输出')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='只输出汇总')

    args = parser.parse_args()

    # 收集所有 MD 文件
    all_files = []
    for path in args.paths:
        files = collect_md_files(path, recursive=args.recursive)
        all_files.extend(files)

    # 去重
    all_files = sorted(set(all_files))

    if not all_files:
        print(f"{Color.RED}❌ 没有找到 Markdown 文件{Color.RESET}")
        sys.exit(1)

    # 分析
    results = []
    for f in all_files:
        result = analyze_file(f)
        if result:
            results.append(result)

    if not results:
        sys.exit(1)

    # ===== JSON 输出 =====
    if args.json:
        output_data = {
            'generated_at': datetime.now().isoformat(),
            'file_count': len(results),
            'files': results,
        }

        json_str = json.dumps(output_data, ensure_ascii=False, indent=2)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(json_str)
            print(f"{Color.GREEN}✅ JSON 已保存: {args.output}{Color.RESET}")
        else:
            print(json_str)
        return

    # ===== 文本输出 =====
    if not args.quiet:
        for r in results:
            print_stats(r['stats'], r['file'], r['file_size'])

    # 汇总
    print_summary(results)

    # 保存到文件
    if args.output:
        write_text_report(results, args.output)


if __name__ == '__main__':
    main()
