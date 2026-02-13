#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GB/GBC ROM 检查器
"""

import sys
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None

# === 精确计算终端显示宽度 ===
try:
    from wcwidth import wcswidth
except ImportError:
    def wcswidth(s):
        return sum(2 if ord(c) > 127 else 1 for c in s)

def pad_to_display_width(text, target_width):
    """补齐到目标显示宽度"""
    current = wcswidth(text)
    if current >= target_width:
        return text
    return text + ' ' * (target_width - current)

def truncate_to_display_width(text, max_width):
    """
    精准截断（符合你的需求）：
    - 保留扩展名 (.gb/.gbc)
    - 末尾保留 4 显示宽度（2中文 或 4英文）
    - 截断部分用 "..." 表示（3个点）
    - 前面显示尽可能多的内容
    """
    if wcswidth(text) <= max_width:
        return text
    
    # 分离扩展名
    if '.' in text and len(text) - text.rfind('.') <= 8:
        ext_start = text.rfind('.')
        base = text[:ext_start]
        ext = text[ext_start:]
    else:
        base = text
        ext = ""
    
    ext_width = wcswidth(ext)
    ellipsis = "..."  # 3个点
    ellipsis_width = wcswidth(ellipsis)  # = 3
    
    # 需要保留的最小宽度：末尾4 + ... + 扩展名
    min_reserve_width = 4 + ellipsis_width + ext_width
    
    # 宽度太小，只保留扩展名和...
    if max_width <= ellipsis_width + ext_width:
        return ellipsis + ext
    
    # 可用于"末尾4宽度+..."的最大空间
    tail_reserve_width = min(4 + ellipsis_width, max_width - ext_width)
    
    # 从右向左提取末尾内容（目标：4显示宽度）
    tail = ""
    tail_width = 0
    for c in reversed(base):
        cw = wcswidth(c)
        if tail_width + cw > 4:
            break
        tail = c + tail
        tail_width += cw
    
    # 计算可用于前缀的最大宽度
    used_width = tail_width + ellipsis_width + ext_width
    prefix_max_width = max_width - used_width
    
    # 从左向右提取前缀（尽可能多）
    prefix = ""
    for c in base:
        if c in tail:  # 避免重复提取末尾部分
            break
        cw = wcswidth(c)
        if wcswidth(prefix) + cw > prefix_max_width:
            break
        prefix += c
    
    # 特殊情况：前缀为空但有空间，提取部分末尾前的内容
    if not prefix and prefix_max_width > 0:
        # 从base开头提取直到遇到tail
        for c in base:
            if prefix + c in base and (prefix + c + tail) in base:
                if wcswidth(prefix + c) <= prefix_max_width:
                    prefix += c
                else:
                    break
    
    return prefix + ellipsis + tail + ext

def get_7za_path():
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, '7za.exe')

def extract_gb_gbc_with_7za(archive_path, out_dir):
    seven_zip = get_7za_path()
    if not os.path.exists(seven_zip):
        return [], "❌ 未找到 7za.exe"
    
    try:
        result = subprocess.run(
            [seven_zip, 'e', str(archive_path), '-r', '*.gb', '*.gbc', f'-o{out_dir}', '-y'],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        if "No files to process" in result.stderr or "No files to process" in result.stdout:
            return [], "压缩包内无 .gb/.gbc"
        
        if result.returncode != 0:
            err = (result.stderr.strip() or result.stdout.strip())[:80]
            return [], f"提取失败: {err}"
        
        roms = []
        for f in Path(out_dir).iterdir():
            if f.is_file() and f.suffix.lower() in ('.gb', '.gbc'):
                roms.append(f)
        return roms, "成功" if roms else "未找到 .gb/.gbc"
    except subprocess.TimeoutExpired:
        return [], "超时"
    except Exception as e:
        return [], f"异常: {e}"

def extract_gb_gbc_from_zip(zip_path, out_dir):
    roms = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            gb_files = [n for n in zf.namelist() if n.lower().endswith(('.gb', '.gbc'))]
            if not gb_files:
                return [], "压缩包内无 .gb/.gbc"
            
            for name in gb_files:
                filename = os.path.basename(name)
                out_path = Path(out_dir) / filename
                
                counter = 1
                stem, suffix = os.path.splitext(filename)
                while out_path.exists():
                    out_path = Path(out_dir) / f"{stem}_{counter}{suffix}"
                    counter += 1
                
                zf.extract(name, out_dir)
                extracted = Path(out_dir) / name
                if extracted != out_path:
                    extracted.rename(out_path)
                roms.append(out_path)
        return roms, "成功"
    except Exception as e:
        return [], f"Zip 提取失败: {e}"

def detect_gb_type(rom_path):
    try:
        with open(rom_path, 'rb') as f:
            f.seek(0x143)
            b = f.read(1)
            if not b: return None
            v = b[0]
            return "GB" if v == 0x00 else "GBC" if v in (0x80, 0xC0) else None
    except:
        return None

def check_rom(rom_path, display_name):
    t = detect_gb_type(rom_path)
    if not t: return (display_name, "⚠️", "?")
    cur_ext = rom_path.suffix.lower()
    exp_ext = ".gb" if t == "GB" else ".gbc"
    status = "✅" if cur_ext == exp_ext else "❌"
    suggest = "" if status == "✅" else exp_ext
    return (display_name, status, suggest)

def collect_from_archive(archive_path, base_tmpdir):
    """关键修复：移除压缩包名前缀添加（原脚本第179-180行）"""
    subdir_name = f"_{archive_path.stem[:20]}_{abs(hash(str(archive_path))) % 10000:04d}"
    tmp_subdir = Path(base_tmpdir) / subdir_name
    tmp_subdir.mkdir(exist_ok=True)
    
    roms = []
    suf = archive_path.suffix.lower()
    
    print(f"  📦 {archive_path.name}")
    
    if suf == '.zip':
        files, msg = extract_gb_gbc_from_zip(archive_path, tmp_subdir)
        if not files:
            print(f"    ⚠️  {msg}")
            return []
        roms = [(f, f.name) for f in files]  # 直接使用文件名
    elif suf == '.7z':
        files, msg = extract_gb_gbc_with_7za(archive_path, tmp_subdir)
        if not files:
            print(f"    ⚠️  {msg}")
            return []
        roms = [(f, f.name) for f in files]  # 直接使用文件名
    else:
        return []
    
    # === 关键：不再添加前缀！===
    return roms

def collect_from_folder(folder):
    roms = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(('.gb', '.gbc')):
                p = Path(root) / f
                try:
                    rel = p.relative_to(folder)
                    disp = str(rel).replace(os.sep, '→')
                except:
                    disp = f
                roms.append((p, disp))
    return roms

def print_table(results):
    if not results:
        print("\n❌ 未找到可识别的 ROM")
        return
    
    NAME_WIDTH = 48
    STATUS_WIDTH = 4
    SUGGEST_WIDTH = 10
    
    header_name = pad_to_display_width("文件名", NAME_WIDTH)
    header_status = "状态".center(STATUS_WIDTH)
    header_suggest = pad_to_display_width("建议扩展名", SUGGEST_WIDTH)
    header = header_name + "  " + header_status + "  " + header_suggest
    
    total_width = wcswidth(header)
    line = "=" * total_width
    
    print("\n" + line)
    print(header)
    print("-" * total_width)
    
    for name, stat, sug in sorted(results, key=lambda x: x[0].lower()):
        truncated = truncate_to_display_width(name, NAME_WIDTH)
        disp_name = pad_to_display_width(truncated, NAME_WIDTH)
        stat_cell = stat.center(STATUS_WIDTH)
        sug_cell = pad_to_display_width(sug, SUGGEST_WIDTH)
        
        print(disp_name + "  " + stat_cell + "  " + sug_cell)
    
    print(line)
    
    total = len(results)
    ok = sum(1 for _, s, _ in results if s == "✅")
    bad = sum(1 for _, s, _ in results if s == "❌")
    unk = total - ok - bad
    print(f"\n📊 统计: 共 {total} 个 | 正确 {ok} | 错误 {bad} | 未知 {unk}")

def main():
    if len(sys.argv) < 2:
        print("💡 用法：拖放 zip/7z/文件夹 到本程序")
        input("\n（按回车退出）")
        return

    inputs = [Path(p).resolve() for p in sys.argv[1:] if Path(p).exists()]
    if not inputs:
        print("❌ 无效路径")
        return

    print("🔍 扫描输入源...")
    all_roms = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for p in inputs:
            suf = p.suffix.lower()
            if suf in ('.zip', '.7z'):
                all_roms.extend(collect_from_archive(p, tmpdir))
            elif p.is_dir():
                print(f"  📂 {p.name}")
                all_roms.extend(collect_from_folder(p))
            elif suf in ('.gb', '.gbc'):
                all_roms.append((p, p.name))
            else:
                print(f"  ⚠️  跳过: {p.name}")

        if not all_roms:
            print("\n❌ 未找到 .gb/.gbc 文件")
            return

        total = len(all_roms)
        print(f"\n✅ 识别 {total} 个 ROM...\n")
        
        # tqdm 进度条
        results = []
        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as executor:
            futures = {executor.submit(check_rom, path, name): None for path, name in all_roms}
            if HAS_TQDM:
                for future in tqdm(as_completed(futures), total=total, desc="  识别中", ncols=80, unit="rom"):
                    results.append(future.result())
            else:
                for future in as_completed(futures):
                    results.append(future.result())
        
        print_table(results)
        input("\n（按回车退出）")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 操作被用户中断")
        input("（按回车退出）")
    except Exception as e:
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        input("\n（按回车退出）")