#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重置 YOLO 推理服务脚本
功能：
1. 查找命令行中包含 yolo_inference.py 的进程
2. 查找占用 TCP 8765 端口的进程
3. 终止这些与 YOLO 服务相关的进程树

说明：
- 本脚本不会清理日志文件
- 本脚本不会删除任何临时图像或目录
- 用于在重启 OpenPnP 前，确保旧的 YOLO 服务不会残留在内存中
"""

import csv
import subprocess
import sys

YOLO_SERVER_PORT = 8765
YOLO_SCRIPT_NAME = "yolo_inference.py"


def run_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            shell=False,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)

 
def get_yolo_processes_by_commandline():
    code, stdout, stderr = run_command([
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Csv -NoTypeInformation",
    ])
    if code != 0:
        print(f"✗ 查询进程命令行失败: {stderr.strip()}")
        return []

    processes = []
    reader = csv.DictReader(stdout.splitlines())
    for row in reader:
        command_line = (row.get("CommandLine") or "").strip()
        process_id = (row.get("ProcessId") or "").strip()
        name = (row.get("Name") or "").strip()
        if not process_id:
            continue
        if YOLO_SCRIPT_NAME.lower() in command_line.lower():
            try:
                processes.append(
                    {
                        "pid": int(process_id),
                        "name": name,
                        "command_line": command_line,
                        "reason": f"命令行包含 {YOLO_SCRIPT_NAME}",
                    }
                )
            except ValueError:
                continue
    return processes


def get_yolo_processes_by_port():
    code, stdout, stderr = run_command(["netstat", "-ano", "-p", "tcp"])
    if code != 0:
        print(f"✗ 查询端口占用失败: {stderr.strip()}")
        return []

    targets = []
    port_suffix = f":{YOLO_SERVER_PORT}"
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("tcp"):
            continue
        parts = stripped.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        state = parts[3]
        pid_text = parts[4]
        if not local_address.endswith(port_suffix):
            continue
        if state.upper() not in ("LISTENING", "ESTABLISHED"):
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        targets.append(
            {
                "pid": pid,
                "name": "",
                "command_line": "",
                "reason": f"占用 TCP 端口 {YOLO_SERVER_PORT}",
            }
        )
    return targets


def merge_processes(*process_groups):
    merged = {}
    for group in process_groups:
        for item in group:
            pid = item["pid"]
            existing = merged.get(pid)
            if existing is None:
                merged[pid] = dict(item)
            else:
                reasons = {existing.get("reason", ""), item.get("reason", "")}
                existing["reason"] = "，".join([r for r in reasons if r])
                if not existing.get("name") and item.get("name"):
                    existing["name"] = item["name"]
                if not existing.get("command_line") and item.get("command_line"):
                    existing["command_line"] = item["command_line"]
    return list(merged.values())


def terminate_process(pid):
    code, stdout, stderr = run_command(["taskkill", "/PID", str(pid), "/F", "/T"])
    if code == 0:
        return True, (stdout or "").strip()
    return False, (stderr or stdout or "").strip()


def main():
    print("=" * 60)
    print("开始重置 YOLO 推理服务...")
    print("=" * 60)

    by_commandline = get_yolo_processes_by_commandline()
    by_port = get_yolo_processes_by_port()
    targets = merge_processes(by_commandline, by_port)

    if not targets:
        print("未发现需要终止的 YOLO 服务进程")
        print("=" * 60)
        return 0

    terminated_count = 0
    for target in targets:
        pid = target["pid"]
        reason = target.get("reason", "")
        name = target.get("name", "")
        command_line = target.get("command_line", "")
        print(f"准备终止 PID={pid} Name={name or 'unknown'} Reason={reason}")
        if command_line:
            print(f"  CommandLine: {command_line}")
        success, message = terminate_process(pid)
        if success:
            print(f"✓ 已终止进程 PID={pid}")
            if message:
                print(f"  {message}")
            terminated_count += 1
        else:
            print(f"✗ 终止进程失败 PID={pid}: {message}")

    print("=" * 60)
    print(f"重置完成！共终止 {terminated_count} 个 YOLO 相关进程")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
