"""
Markdown 按二级标题数量切分工具

规则：
    - 以一级标题（#）为章节边界
    - 累加每个章节的二级标题（##）数量
    - 当"累计数 + 当前章节数 > 阈值"时，先输出已累计部分，从当前章节开始新文件
    - 文件名用该文件的第一个一级标题命名

依赖：无（纯标准库）

用法：
    # 每累计 100 个二级标题切一个文件
    python split_md.py input.md --max-h2 100

    # 预览
    python split_md.py input.md --max-h2 100 --dry-run

    # 指定输出目录
    python split_md.py input.md --max-h2 100 -o ./output

    # 批量处理目录
    python split_md.py ./md_files/ --batch --max-h2 100
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Optional, Tuple, Dict
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


# ============ 标题解析 ============
RE_HEADING = re.compile(r'^(#{1,6})\s+(.*)$')


def parse_heading(line: str) -> Optional[Tuple[int, str]]:
    """解析标题行，返回 (级别, 文本)"""
    m = RE_HEADING.match(line)
    if m:
        return len(m.group(1)), m.group(2).strip()
    return None


# ============ 章节切分 ============
class Section:
    """一个一级标题章节"""
    def __init__(self, start_idx: int, level: int, title: str):
        self.start_idx = start_idx        # 起始行号
        self.level = level                # 标题级别
        self.title = title                # 标题文本
        self.end_idx = start_idx          # 结束行号（不含）
        self.h2_count = 0                 # 本章节内二级标题数
        self.h3_count = 0


def split_into_sections(lines: List[str]) -> Tuple[List[str], List[Section]]:
    """
    把文档按一级标题切成章节。

    :return: (文档头部内容, 章节列表)
             文档头部 = 第一个一级标题之前的所有内容
    """
    sections: List[Section] = []
    head_lines: List[str] = []

    current: Optional[Section] = None

    for i, line in enumerate(lines):
        heading = parse_heading(line)

        if heading:
            level, title = heading

            if level == 1:
                # 遇到一级标题：结束上一个章节
                if current is not None:
                    current.end_idx = i
                    sections.append(current)
                elif i > 0:
                    # 第一个一级标题之前的内容
                    head_lines = lines[:i]

                # 开始新章节
                current = Section(i, level, title)
                continue

            # 二级标题：计数
            if level == 2 and current is not None:
                current.h2_count += 1
            elif level == 3 and current is not None:
                current.h3_count += 1

    # 最后一个章节
    if current is not None:
        current.end_idx = len(lines)
        sections.append(current)
    elif not sections:
        # 没有一级标题，整个文档作为头部
        head_lines = lines

    return head_lines, sections


# ============ 分组逻辑 ============
def group_sections(sections: List[Section],
                    max_h2: int) -> List[List[Section]]:
    """
    按二级标题数量分组。

    规则：
        累加当前章节的 h2_count
        当"累计 + 当前章节数 > max_h2"时：
            - 先输出已累计的章节（一组）
            - 从当前章节开始新的一组

    :param max_h2: 每组最多包含的二级标题数（软上限）
    :return: 分组列表
    """
    if not sections:
        return []

    groups: List[List[Section]] = []
    current_group: List[Section] = []
    current_count = 0

    for section in sections:
        # 如果当前章节加入后超过上限，且当前组非空，则先输出
        if current_group and current_count + section.h2_count > max_h2:
            groups.append(current_group)
            current_group = []
            current_count = 0

        current_group.append(section)
        current_count += section.h2_count

    # 最后一组
    if current_group:
        groups.append(current_group)

    return groups


# ============ 文件名生成 ============
def sanitize_filename(name: str, max_len: int = 80) -> str:
    """
    把标题转成合法文件名：
    - 去掉 / \ : * ? " < > |
    - 去掉首尾空格和点
    - 限制长度
    """
    # 去掉 Markdown 格式符号
    name = re.sub(r'[*_`~]', '', name)
    # 去掉非法字符
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    # 去掉首尾空格和点
    name = name.strip(' .')
    # 多个空格合并
    name = re.sub(r'\s+', ' ', name)
    # 长度限制
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    # 空标题兜底
    if not name:
        name = 'untitled'
    return name


def make_output_filename(group: List[Section],
                          part_index: int,
                          total_parts: int,
                          extension: str = '.md') -> str:
    """
    根据分组内的第一个一级标题生成文件名。

    如果有重名，加序号。
    """
    if not group:
        return f"part_{part_index:03d}{extension}"

    first_title = group[0].title
    base = sanitize_filename(first_title)

    # 如果分组里只有 1 个章节，且总分组数 > 1，直接使用标题
    # 否则加序号避免重名（在后续去重阶段处理）
    return f"{base}{extension}"


# ============ 生成文件内容 ============
def build_file_content(head_lines: List[str],
                        group: List[Section],
                        all_lines: List[str],
                        include_head: bool = False) -> str:
    """
    构建一个输出文件的内容。

    :param head_lines: 文档头部（第一个一级标题之前的内容）
    :param group: 本章节分组
    :param all_lines: 原始所有行
    :param include_head: 是否包含文档头部
    :return: 文件内容
    """
    result = []

    # 包含文档头部（一般只有第一个文件包含）
    if include_head and head_lines:
        result.extend(head_lines)
        # 确保头部和第一个章节之间有分隔
        if result and result[-1].strip():
            result.append('')

    for section in group:
        # 提取章节内容
        for i in range(section.start_idx, section.end_idx):
            result.append(all_lines[i])

        # 章节之间确保有空行分隔
        if result and result[-1].strip():
            result.append('')

    # 去掉末尾多余空行
    while result and not result[-1].strip():
        result.pop()

    return '\n'.join(result) + '\n'


# ============ 主处理 ============
def split_markdown_file(input_path: str,
                         output_dir: str,
                         max_h2: int,
                         dry_run: bool = False,
                         verbose: bool = False,
                         include_head: bool = True) -> dict:
    """
    切分单个 MD 文件。

    :param max_h2: 每个文件最多累计的二级标题数
    :param include_head: 第一个文件是否包含文档头部
    :return: 统计信息
    """
    input_path = Path(input_path).resolve()

    if not input_path.exists():
        print(f"{Color.RED}❌ 文件不存在: {input_path}{Color.RESET}")
        return {}

    # 读取
    try:
        content = input_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        content = input_path.read_text(encoding='gbk')

    lines = content.split('\n')

    # 按一级标题切章节
    head_lines, sections = split_into_sections(lines)

    if not sections:
        print(f"{Color.YELLOW}⚠️  文件中没有一级标题（#），无法切分{Color.RESET}")
        return {}

    # 统计
    total_h2 = sum(s.h2_count for s in sections)

    # 分组
    groups = group_sections(sections, max_h2)

    # 输出目录
    output_path = Path(output_dir).resolve()
    if not dry_run:
        output_path.mkdir(parents=True, exist_ok=True)

    # ===== 打印概要 =====
    print(f"\n{Color.CYAN}{'='*80}{Color.RESET}")
    print(f"{Color.BOLD}📄 {input_path.name}{Color.RESET}")
    print(f"{Color.CYAN}{'='*80}{Color.RESET}")
    print(f"   总行数:       {len(lines):,}")
    print(f"   一级标题数:   {len(sections):,}")
    print(f"   二级标题总数: {total_h2:,}")
    print(f"   每文件上限:   {max_h2:,} 个二级标题")
    print(f"   将分成:       {Color.BOLD}{len(groups)}{Color.RESET} 个文件")

    if verbose:
        print(f"\n   {Color.DIM}章节列表:{Color.RESET}")
        for i, s in enumerate(sections, 1):
            print(f"     [{i:>3}] h2={s.h2_count:>3}  {s.title[:60]}")

    # ===== 生成文件 =====
    print(f"\n{Color.CYAN}{'='*80}{Color.RESET}")
    if dry_run:
        print(f"{Color.BOLD}🔎 DRY-RUN 预览（不写文件）{Color.RESET}")
    else:
        print(f"{Color.BOLD}✂️  开始切分{Color.RESET}")
    print(f"{Color.CYAN}{'='*80}{Color.RESET}\n")

    # 用集合记录已使用的文件名，避免重名
    used_names = set()
    file_infos = []

    for i, group in enumerate(groups, 1):
        # 生成文件名
        base_name = make_output_filename(group, i, len(groups),
                                          extension=input_path.suffix)
        # 去重
        name = base_name
        counter = 1
        while name.lower() in used_names:
            stem = Path(base_name).stem
            ext = Path(base_name).suffix
            name = f"{stem}_{counter}{ext}"
            counter += 1
        used_names.add(name.lower())

        output_file = output_path / name

        # 统计
        group_h2 = sum(s.h2_count for s in group)
        group_lines = sum(s.end_idx - s.start_idx for s in group)
        group_titles = [s.title for s in group]

        # 内容
        file_content = build_file_content(
            head_lines if (i == 1 and include_head) else [],
            group, lines, include_head=(i == 1 and include_head)
        )
        char_count = len(file_content)
        line_count = file_content.count('\n')

        info = {
            'index': i,
            'output': str(output_file),
            'output_name': name,
            'sections': group_titles,
            'section_count': len(group),
            'h2_count': group_h2,
            'lines': group_lines,
            'chars': char_count,
        }
        file_infos.append(info)

        # 打印
        print(f"{Color.BOLD}[{i:>3}/{len(groups)}]{Color.RESET} "
              f"{Color.GREEN}{name}{Color.RESET}")
        print(f"      章节数: {len(group)}  |  "
              f"二级标题: {group_h2}  |  "
              f"行数: {group_lines:,}  |  "
              f"字符: {char_count:,}")
        print(f"      {Color.DIM}包含章节:{Color.RESET}")
        for t in group_titles[:5]:
            print(f"         · {t[:70]}")
        if len(group_titles) > 5:
            print(f"         {Color.DIM}... 还有 {len(group_titles) - 5} 个{Color.RESET}")

        # 写文件
        if not dry_run:
            try:
                output_file.write_text(file_content, encoding='utf-8')
                print(f"      {Color.GREEN}✅ 已保存{Color.RESET}")
            except Exception as e:
                print(f"      {Color.RED}❌ 保存失败: {e}{Color.RESET}")
                info['error'] = str(e)

        print()

    # ===== 汇总 =====
    total_chars = sum(f['chars'] for f in file_infos)

    print(f"{Color.CYAN}{'='*80}{Color.RESET}")
    if dry_run:
        print(f"{Color.BOLD}📊 DRY-RUN 汇总{Color.RESET}")
    else:
        print(f"{Color.BOLD}📊 切分汇总{Color.RESET}")
    print(f"{Color.CYAN}{'='*80}{Color.RESET}")
    print(f"   输入文件:     {input_path.name}")
    print(f"   输出文件数:   {Color.BOLD}{len(file_infos)}{Color.RESET}")
    print(f"   二级标题总数: {total_h2:,}")
    print(f"   每文件上限:   {max_h2:,}")
    print(f"   总字符数:     {total_chars:,}")

    # 表格
    print(f"\n   {'#':>4}  {'文件名':<45} {'章节':>5}  {'h2':>5}  {'字符':>10}")
    print(f"   {'-'*4}  {'-'*45} {'-'*5}  {'-'*5}  {'-'*10}")
    for f in file_infos:
        name_display = f['output_name']
        if len(name_display) > 43:
            name_display = name_display[:40] + '...'
        print(f"   {f['index']:>4}  {name_display:<45} "
              f"{f['section_count']:>5}  {f['h2_count']:>5}  "
              f"{f['chars']:>10,}")

    if dry_run:
        print(f"\n{Color.YELLOW}💡 这是预览模式，未实际写文件{Color.RESET}")
        print(f"{Color.YELLOW}   去掉 --dry-run 参数即可执行实际切分{Color.RESET}")

    return {
        'input': str(input_path),
        'total_sections': len(sections),
        'total_h2': total_h2,
        'total_files': len(file_infos),
        'total_chars': total_chars,
        'files': file_infos,
        'dry_run': dry_run,
    }


# ============ 批量处理 ============
def process_directory(input_dir: str,
                       output_dir: str,
                       max_h2: int,
                       dry_run: bool = False,
                       verbose: bool = False) -> List[dict]:
    """批量处理目录下的 MD 文件"""
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
        # 每个文件输出到单独的子目录
        sub_output = Path(output_dir) / md_file.stem
        result = split_markdown_file(
            str(md_file),
            str(sub_output),
            max_h2=max_h2,
            dry_run=dry_run,
            verbose=verbose,
        )
        if result:
            results.append(result)

    # 汇总
    print(f"\n{Color.CYAN}{'='*80}{Color.RESET}")
    print(f"{Color.BOLD}📊 批量处理汇总{Color.RESET}")
    print(f"{Color.CYAN}{'='*80}{Color.RESET}")

    total_files = sum(r['total_files'] for r in results)
    total_h2 = sum(r['total_h2'] for r in results)
    total_chars = sum(r['total_chars'] for r in results)

    print(f"   处理文件数:   {len(results)}")
    print(f"   输出文件数:   {total_files}")
    print(f"   二级标题总数: {total_h2:,}")
    print(f"   总字符数:     {total_chars:,}")

    return results


# ============ 命令行 ============
def main():
    enable_windows_ansi()

    parser = argparse.ArgumentParser(
        description='Markdown 按二级标题数量切分工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{Color.BOLD}切割规则:{Color.RESET}

  - 以一级标题（#）为章节边界
  - 累加每个章节的二级标题（##）数量
  - 当"累计 + 当前章节数 > 阈值"时，先输出已累计部分，从当前章节开始新文件
  - 文件名用该文件的第一个一级标题

{Color.BOLD}示例:{Color.RESET}

  {Color.CYAN}# 每累计 100 个二级标题切一个文件{Color.RESET}
  python split_md.py input.md --max-h2 100

  {Color.CYAN}# 预览{Color.RESET}
  python split_md.py input.md --max-h2 100 --dry-run

  {Color.CYAN}# 指定输出目录{Color.RESET}
  python split_md.py input.md --max-h2 100 -o ./output

  {Color.CYAN}# 批量处理目录{Color.RESET}
  python split_md.py ./md_files/ --batch --max-h2 100

  {Color.CYAN}# 不包含文档头部（第一个一级标题之前的内容）{Color.RESET}
  python split_md.py input.md --max-h2 100 --no-head
        """
    )

    parser.add_argument('input', help='输入 MD 文件或目录')
    parser.add_argument('--max-h2', '-m', type=int, default=100,
                        help='每个文件最多累计的二级标题数（默认 100）')
    parser.add_argument('-o', '--output', default=None,
                        help='输出目录（默认 ./split_output）')
    parser.add_argument('--batch', action='store_true',
                        help='批量处理目录')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='预览模式，不写文件')
    parser.add_argument('--no-head', action='store_true',
                        help='不包含文档头部（第一个一级标题之前的内容）')
    parser.add_argument('--verbose', '-V', action='store_true',
                        help='显示详细信息')

    args = parser.parse_args()

    if args.max_h2 < 1:
        print(f"{Color.RED}❌ --max-h2 必须大于 0{Color.RESET}")
        sys.exit(1)

    # 默认输出目录
    if args.output is None:
        input_p = Path(args.input)
        if input_p.is_file():
            args.output = str(input_p.parent / f"{input_p.stem}_split")
        else:
            args.output = './split_output'

    # 批量模式
    if args.batch or os.path.isdir(args.input):
        process_directory(
            args.input, args.output, args.max_h2,
            dry_run=args.dry_run, verbose=args.verbose,
        )
    else:
        split_markdown_file(
            args.input, args.output, args.max_h2,
            dry_run=args.dry_run, verbose=args.verbose,
            include_head=not args.no_head,
        )


if __name__ == '__main__':
    main()
