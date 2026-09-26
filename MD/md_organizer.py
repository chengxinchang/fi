"""
Markdown 对话记录整理脚本

处理规则：
1. 从 ## User: 下方的 > 日期 引用块提取日期，生成一级标题 # 2026-04-29
2. ## User: 改为二级标题，内容取正文前 N 个字（不含 User: 和日期）
3. ## Gemini: 降级为 ### Gemini:，其下级标题整体降级
4. 日期变化时插入新的一级日期标题

依赖：
    pip install pyyaml

用法：
    python md_organizer.py input.md --dry-run
    python md_organizer.py input.md
    python md_organizer.py input.md -c my_config.yaml
    python md_organizer.py ./md_files/ --batch
"""

import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Dict

try:
    import yaml
except ImportError:
    print("❌ 缺少 pyyaml，请先安装：")
    print("   pip install pyyaml")
    sys.exit(1)


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
            kernel32.SetStdHandle(-11, kernel32.GetStdHandle(-11))
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            for attr in dir(Color):
                if not attr.startswith('_'):
                    setattr(Color, attr, '')


# ============ 默认配置 ============
DEFAULT_CONFIG = {
    'keywords': {
        'user': ['User:', '用户:'],
        'gemini': ['Gemini:', '助手:'],
    },
    'quote_prefix': '>',
    'title_truncate': 30,
    'date_formats': [
        '%m/%d/%Y %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y/%m/%d %H:%M:%S',
        '%m/%d/%Y',
        '%Y-%m-%d',
    ],
    'date_heading_format': '%Y-%m-%d',
    'output': {
        'suffix': '_organized',
        'new_file': True,
    },
    'options': {
        'keep_date_quote': True,
        'date_unknown': '0000-00-00',
    },
}


def load_config(config_path: Optional[str]) -> dict:
    """加载配置文件"""
    import copy
    config = copy.deepcopy(DEFAULT_CONFIG)

    if config_path and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}

        for key, value in user_config.items():
            if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                config[key].update(value)
            else:
                config[key] = value

    return config


# ============ 标题解析 ============
def parse_heading(line: str) -> Optional[Tuple[int, str]]:
    """解析 Markdown 标题行"""
    m = re.match(r'^(#{1,6})\s+(.*)$', line)
    if m:
        return len(m.group(1)), m.group(2).strip()
    return None


def is_quote_line(line: str, quote_prefix: str = '>') -> bool:
    """判断是否是引用块行"""
    return line.strip().startswith(quote_prefix)


def extract_quote_content(line: str, quote_prefix: str = '>') -> str:
    """提取引用块内容（去掉 > 前缀）"""
    stripped = line.strip()
    if stripped.startswith(quote_prefix):
        return stripped[len(quote_prefix):].strip()
    return stripped


# ============ 日期提取 ============
def extract_date_from_text(text: str,
                            date_formats: List[str]) -> Optional[datetime]:
    """从文本中提取日期"""
    if not text:
        return None

    for fmt in date_formats:
        pattern = _date_format_to_regex(fmt)
        m = re.search(pattern, text)
        if m:
            date_str = m.group(0)
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

    return None


def _date_format_to_regex(fmt: str) -> str:
    """strftime 格式 → 正则"""
    replacements = [
        ('%Y', r'\d{4}'),
        ('%m', r'\d{1,2}'),
        ('%d', r'\d{1,2}'),
        ('%H', r'\d{1,2}'),
        ('%M', r'\d{1,2}'),
        ('%S', r'\d{1,2}'),
    ]
    pattern = re.escape(fmt)
    for k, v in replacements:
        pattern = pattern.replace(re.escape(k), v)
    return pattern


# ============ 关键字匹配 ============
def match_keyword(text: str, keyword_list: List[str]) -> Optional[str]:
    """检查文本是否以某个关键字开头"""
    text_stripped = text.strip()
    for kw in keyword_list:
        if text_stripped.startswith(kw):
            return kw
    return None


# ============ 结构化解析 ============
class Block:
    """一个对话块（从 ## User: 或 ## Gemini: 开始）"""
    def __init__(self, heading_idx: int, level: int, heading_text: str,
                 block_type: str):
        self.heading_idx = heading_idx      # 标题所在行号
        self.level = level                  # 标题级别
        self.heading_text = heading_text    # 标题原文
        self.block_type = block_type        # 'user' | 'gemini' | 'other'
        self.date_quote_idx: Optional[int] = None  # 日期引用块行号
        self.date: Optional[datetime] = None       # 解析出的日期
        self.content_start: int = heading_idx + 1  # 内容起始行
        self.content_end: int = heading_idx + 1    # 内容结束行（不含）
        self.first_content_line: str = ''          # 正文第一行非空内容


def parse_blocks(lines: List[str],
                 user_keywords: List[str],
                 gemini_keywords: List[str]) -> List[Block]:
    """
    扫描全文，识别出所有 ## User: / ## Gemini: 块。
    """
    blocks = []
    current_block: Optional[Block] = None

    for i, line in enumerate(lines):
        heading = parse_heading(line)

        if heading:
            level, text = heading

            # 检查是否是 User 或 Gemini 标题
            kw_user = match_keyword(text, user_keywords)
            kw_gemini = match_keyword(text, gemini_keywords)

            if kw_user:
                # 结束上一个块
                if current_block is not None:
                    current_block.content_end = i
                    blocks.append(current_block)

                # 创建新块
                current_block = Block(i, level, text, 'user')
                continue

            if kw_gemini:
                if current_block is not None:
                    current_block.content_end = i
                    blocks.append(current_block)

                current_block = Block(i, level, text, 'gemini')
                continue

            # 其他标题：如果属于当前块，不作为新块
            # 但要记录，用于后续降级
            if current_block is not None:
                # 其他标题仍在当前块内
                pass
            continue

    # 最后一个块
    if current_block is not None:
        current_block.content_end = len(lines)
        blocks.append(current_block)

    return blocks


def fill_block_details(block: Block,
                       lines: List[str],
                       date_formats: List[str],
                       quote_prefix: str = '>'):
    """
    为每个块填充：
    - 日期引用块位置
    - 日期对象
    - 正文第一行非空内容
    """
    # 找日期引用块（标题后往下找）
    for i in range(block.heading_idx + 1, block.content_end):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            continue

        # 只看引用块
        if is_quote_line(line, quote_prefix):
            content = extract_quote_content(line, quote_prefix)
            date = extract_date_from_text(content, date_formats)
            if date:
                block.date_quote_idx = i
                block.date = date
                break
            # 不是日期，继续找
            continue

        # 遇到非引用块的非空行，停止查找
        # （但可能日期引用块后面有空行再引用块，这里允许跳过空行）
        # 如果已经找了超过 5 行还没找到，就放弃
        if i - block.heading_idx > 5:
            break

    # 找正文第一行非空内容（用于 User 标题）
    # 跳过：空行、日期引用块、Thinking 引用块
    for i in range(block.heading_idx + 1, block.content_end):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            continue

        # 跳过引用块
        if is_quote_line(line, quote_prefix):
            continue

        # 跳过水平线
        if re.match(r'^[-*_]{3,}$', stripped):
            continue

        # 找到正文
        block.first_content_line = stripped
        break


# ============ 生成新内容 ============
def process_markdown(content: str,
                      config: dict,
                      verbose: bool = False) -> Tuple[str, dict]:
    """
    处理 Markdown 内容。

    :return: (新内容, 统计信息)
    """
    lines = content.split('\n')

    user_keywords = config['keywords']['user']
    gemini_keywords = config['keywords']['gemini']
    quote_prefix = config['quote_prefix']
    truncate = config['title_truncate']
    date_formats = config['date_formats']
    date_heading_format = config['date_heading_format']
    keep_date_quote = config['options']['keep_date_quote']
    date_unknown = config['options']['date_unknown']

    # 解析块
    blocks = parse_blocks(lines, user_keywords, gemini_keywords)

    for b in blocks:
        fill_block_details(b, lines, date_formats, quote_prefix)

    # 统计
    stats = {
        'total_lines': len(lines),
        'blocks': len(blocks),
        'user_blocks': sum(1 for b in blocks if b.block_type == 'user'),
        'gemini_blocks': sum(1 for b in blocks if b.block_type == 'gemini'),
        'date_headings': 0,
        'dates_found': sum(1 for b in blocks if b.date),
        'demoted_headings': 0,
    }

    # ===== 构建输出 =====
    output: List[str] = []

    # 头部：第一个块之前的原始内容（保留）
    if blocks:
        head_end = blocks[0].heading_idx
        for i in range(head_end):
            output.append(lines[i])

    current_date: Optional[str] = None

    for block_idx, block in enumerate(blocks):
        # ===== 1. 日期变化 → 插入一级日期标题 =====
        date_str = None
        if block.date:
            date_str = block.date.strftime(date_heading_format)
        else:
            date_str = date_unknown

        if date_str != current_date:
            # 插入新的一级日期标题
            if output and output[-1].strip():
                output.append('')
            output.append(f"# {date_str}")
            output.append('')
            current_date = date_str
            stats['date_headings'] += 1

        # ===== 2. 处理当前块 =====
        if block.block_type == 'user':
            # User 块：标题改为正文前 N 字
            new_title = truncate_text(block.first_content_line, truncate)
            if not new_title:
                new_title = "(空)"

            output.append(f"## {new_title}")
            output.append('')

            # 输出标题下方的引用块（日期、其他引用）
            # 以及正文内容
            for i in range(block.heading_idx + 1, block.content_end):
                line = lines[i]

                # 日期引用块：根据配置决定是否保留
                if i == block.date_quote_idx:
                    if keep_date_quote:
                        output.append(line)
                    continue

                output.append(line)

        elif block.block_type == 'gemini':
            # Gemini 块：降级为三级
            output.append(f"### Gemini:")
            output.append('')

            for i in range(block.heading_idx + 1, block.content_end):
                line = lines[i]

                # 日期引用块
                if i == block.date_quote_idx:
                    if keep_date_quote:
                        output.append(line)
                    continue

                # 检查是否是标题，需要降级
                heading = parse_heading(line)
                if heading:
                    lvl, txt = heading
                    new_lvl = min(lvl + 1, 6)
                    output.append(f"{'#' * new_lvl} {txt}")
                    stats['demoted_headings'] += 1
                    continue

                # 其他行原样输出
                output.append(line)

        # 块之间加空行（如果下一行不是空行）
        if block_idx < len(blocks) - 1:
            if output and output[-1].strip():
                output.append('')

    new_content = '\n'.join(output)
    return new_content, stats


def truncate_text(text: str, n: int) -> str:
    """截取文本前 N 个字"""
    if not text:
        return ''
    # 去掉 Markdown 引用符号、加粗等
    text = re.sub(r'^[>\s]+', '', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = text.strip()

    if len(text) > n:
        return text[:n] + '...'
    return text


# ============ 文件处理 ============
def process_file(input_path: str,
                 config: dict,
                 output_path: Optional[str] = None,
                 dry_run: bool = False,
                 verbose: bool = False) -> dict:
    """处理单个 MD 文件"""
    input_path = Path(input_path).resolve()

    if not input_path.exists():
        print(f"{Color.RED}❌ 文件不存在: {input_path}{Color.RESET}")
        return {}

    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content, stats = process_markdown(content, config, verbose)

    # 输出路径
    if output_path is None:
        if config['output']['new_file']:
            suffix = config['output']['suffix']
            output_path = input_path.parent / f"{input_path.stem}{suffix}{input_path.suffix}"
        else:
            output_path = input_path

    output_path = Path(output_path)

    # 统计
    print(f"\n{Color.CYAN}{'='*70}{Color.RESET}")
    print(f"{Color.BOLD}📄 {input_path.name}{Color.RESET}")
    print(f"{Color.CYAN}{'='*70}{Color.RESET}")
    print(f"   总行数:       {stats['total_lines']}")
    print(f"   对话块:       {stats['blocks']} "
          f"(User: {stats['user_blocks']}, Gemini: {stats['gemini_blocks']})")
    print(f"   提取日期数:   {Color.GREEN}{stats['dates_found']}{Color.RESET}")
    print(f"   一级日期标题: {Color.GREEN}{stats['date_headings']}{Color.RESET}")
    print(f"   降级标题:     {stats['demoted_headings']}")

    if dry_run:
        print(f"\n{Color.YELLOW}🔎 DRY-RUN 模式，不写文件{Color.RESET}")

        # 显示新内容的前 80 行
        preview = new_content.split('\n')
        preview_limit = 80

        print(f"\n{Color.DIM}--- 新内容预览（前 {preview_limit} 行）---{Color.RESET}")
        for line in preview[:preview_limit]:
            print(f"{Color.DIM}│{Color.RESET} {line}")
        if len(preview) > preview_limit:
            print(f"{Color.DIM}│ ... 还有 {len(preview) - preview_limit} 行{Color.RESET}")

    else:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"\n{Color.GREEN}✅ 已保存: {output_path}{Color.RESET}")

    return {
        'input': str(input_path),
        'output': str(output_path),
        'stats': stats,
    }


def process_directory(input_dir: str,
                      config: dict,
                      dry_run: bool = False,
                      verbose: bool = False) -> List[dict]:
    """批量处理目录"""
    input_path = Path(input_dir).resolve()

    if not input_path.is_dir():
        print(f"{Color.RED}❌ 目录不存在: {input_dir}{Color.RESET}")
        return []

    md_files = sorted(input_path.glob('*.md')) + sorted(input_path.glob('*.markdown'))

    if not md_files:
        print(f"{Color.YELLOW}⚠️  目录下没有 MD 文件{Color.RESET}")
        return []

    print(f"{Color.CYAN}📦 找到 {len(md_files)} 个 MD 文件{Color.RESET}")

    results = []
    for md_file in md_files:
        result = process_file(str(md_file), config,
                              dry_run=dry_run, verbose=verbose)
        if result:
            results.append(result)

    # 汇总
    print(f"\n{Color.CYAN}{'='*70}{Color.RESET}")
    print(f"{Color.BOLD}📊 批量处理汇总{Color.RESET}")
    print(f"{Color.CYAN}{'='*70}{Color.RESET}")

    total_dates = sum(r['stats']['date_headings'] for r in results)
    total_blocks = sum(r['stats']['blocks'] for r in results)
    total_demoted = sum(r['stats']['demoted_headings'] for r in results)

    print(f"   处理文件数:   {len(results)}")
    print(f"   对话块总数:   {total_blocks}")
    print(f"   一级日期标题: {total_dates}")
    print(f"   降级标题:     {total_demoted}")

    return results


# ============ 命令行 ============
def main():
    enable_windows_ansi()

    parser = argparse.ArgumentParser(
        description='Markdown 对话记录整理脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{Color.BOLD}处理规则:{Color.RESET}

  1. 从 ## User: 下方的 > 日期 引用块提取日期
  2. 生成一级日期标题 # 2026-04-29
  3. ## User: 改为二级标题，内容取正文前 N 字
  4. ## Gemini: 降级为 ### Gemini:，其下级整体降级
  5. 日期变化时插入新的一级日期标题

{Color.BOLD}示例:{Color.RESET}

  {Color.CYAN}# 预览{Color.RESET}
  python md_organizer.py input.md --dry-run

  {Color.CYAN}# 处理{Color.RESET}
  python md_organizer.py input.md

  {Color.CYAN}# 指定配置{Color.RESET}
  python md_organizer.py input.md -c my_config.yaml

  {Color.CYAN}# 批量{Color.RESET}
  python md_organizer.py ./md_files/ --batch

  {Color.CYAN}# 生成默认配置{Color.RESET}
  python md_organizer.py --init-config
        """
    )

    parser.add_argument('input', nargs='?', help='输入 MD 文件或目录')
    parser.add_argument('-c', '--config', default='md_organizer.yaml',
                        help='配置文件（默认 md_organizer.yaml）')
    parser.add_argument('-o', '--output', default=None,
                        help='输出文件路径（单文件模式）')
    parser.add_argument('--batch', action='store_true',
                        help='批量处理目录')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='预览模式，不写文件')
    parser.add_argument('--verbose', '-V', action='store_true',
                        help='显示详细信息')
    parser.add_argument('--init-config', action='store_true',
                        help='生成默认配置文件')

    args = parser.parse_args()

    if args.init_config:
        with open('md_organizer.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True,
                      default_flow_style=False, sort_keys=False)
        print(f"{Color.GREEN}✅ 已生成默认配置: md_organizer.yaml{Color.RESET}")
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config)

    print(f"{Color.CYAN}⚙️  配置:{Color.RESET}")
    print(f"   User 关键字:   {config['keywords']['user']}")
    print(f"   Gemini 关键字: {config['keywords']['gemini']}")
    print(f"   截取字数:      {config['title_truncate']}")
    print(f"   保留日期引用:  {config['options']['keep_date_quote']}")

    if args.batch or os.path.isdir(args.input):
        process_directory(args.input, config,
                          dry_run=args.dry_run, verbose=args.verbose)
    else:
        process_file(args.input, config, output_path=args.output,
                     dry_run=args.dry_run, verbose=args.verbose)


if __name__ == '__main__':
    main()
