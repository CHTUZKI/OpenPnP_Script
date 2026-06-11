#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" 
清理日志和临时文件脚本
删除以下文件和文件夹内容：
1. BulkFeederScript.log
2. yolo_inference.log
3. log/ 文件夹中的所有文件（OpenPnP.log 只清空内容，保留文件）
4. org.openpnp.vision.pipeline.stages.ImageWriteDebug/ 文件夹中的所有文件
"""
   
import os
import sys
from pathlib import Path

# 获取脚本所在目录（openPNP_Script）
SCRIPT_DIR = Path(__file__).parent.absolute()
OPENPNP_ROOT = SCRIPT_DIR.parent  # .openpnp2 目录

 # 要清理的文件和文件夹
CLEANUP_TARGETS = [
    # 1. BulkFeederScript.log
    SCRIPT_DIR / "BulkFeederScript.log",
    
    # 2. yolo_inference.log
    SCRIPT_DIR / "yolo_inference.log",
    
    # 3. log/ 文件夹
    OPENPNP_ROOT / "log",
    
    # 4. org.openpnp.vision.pipeline.stages.ImageWriteDebug/ 文件夹
    OPENPNP_ROOT / "org.openpnp.vision.pipeline.stages.ImageWriteDebug",
]

# 可选：也清理 temp_images
OPTIONAL_CLEANUP = [
    SCRIPT_DIR / "temp_images",
]


def delete_file(file_path):
    """删除单个文件"""
    try:
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            print(f"✓ 已删除文件: {file_path}")
            return True
        else:
            print(f" 文件不存在或不是文件: {file_path}")
            return False
    except Exception as e:
        print(f"✗ 删除文件失败 {file_path}: {e}")
        return False


def clear_file_contents(file_path):
    """清空文件内容但保留文件"""
    try:
        if file_path.exists() and file_path.is_file():
            # 打开文件并以写入模式清空内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.truncate(0)
            print(f"✓ 已清空文件内容: {file_path}")
            return True
        else:
            print(f" 文件不存在: {file_path}")
            return False
    except Exception as e:
        print(f"✗ 清空文件内容失败 {file_path}: {e}")
        return False


def delete_directory_contents(dir_path):
    """删除文件夹中的所有文件（保留文件夹本身）"""
    try:
        if not dir_path.exists():
            print(f" 文件夹不存在: {dir_path}")
            return 0
        
        if not dir_path.is_dir():
            print(f" 路径不是文件夹: {dir_path}")
            return 0
        
        deleted_count = 0
        openpnp_log_file = dir_path / "OpenPnP.log"
        
        for item in dir_path.iterdir():
            try:
                if item == openpnp_log_file:
                    # 特殊处理 OpenPnP.log：只清空内容，不删除文件
                    if clear_file_contents(item):
                        deleted_count += 1
                elif item.is_file():
                    item.unlink()
                    print(f"✓ 已删除文件: {item.name}")
                    deleted_count += 1
                elif item.is_dir():
                    # 递归删除子文件夹
                    import shutil
                    shutil.rmtree(item)
                    print(f"✓ 已删除文件夹: {item.name}")
                    deleted_count += 1
            except Exception as e:
                print(f"✗ 删除失败 {item.name}: {e}")
        
        return deleted_count
    except Exception as e:
        print(f"✗ 处理文件夹失败 {dir_path}: {e}")
        return 0


def main():
    """主函数"""
    print("=" * 60)
    print("开始清理日志和临时文件...")
    print("=" * 60)
    print()
    
    total_deleted = 0
    
    # 清理主要目标
    for target in CLEANUP_TARGETS:
        print(f"\n处理: {target}")
        print("-" * 60)
        
        if target.is_file():
            # 如果是文件，直接删除
            if delete_file(target):
                total_deleted += 1
        elif target.is_dir():
            # 如果是文件夹，删除其中的所有内容
            count = delete_directory_contents(target)
            total_deleted += count
            if count > 0:
                print(f"  共删除 {count} 个项目")
        else:
            print(f"  路径不存在: {target}")
    
    # 直接清理可选文件
    print("\n" + "=" * 60)
    print("清理可选文件...")
    for item in OPTIONAL_CLEANUP:
        if item.exists():
            if item.is_file():
                if delete_file(item):
                    total_deleted += 1
            elif item.is_dir():
                import shutil
                try:
                    shutil.rmtree(item)
                    print(f"✓ 已删除文件夹: {item}")
                    total_deleted += 1
                except Exception as e:
                    print(f"✗ 删除文件夹失败 {item}: {e}")
    
    # 总结
    print("\n" + "=" * 60)
    print(f"清理完成！共删除 {total_deleted} 个项目")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 