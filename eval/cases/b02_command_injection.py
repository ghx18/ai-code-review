"""评估用例 b02 — 安全：命令注入（shell 拼接用户输入）"""
import subprocess


def backup(dir_path: str):
    subprocess.call("tar -czf backup.tar.gz " + dir_path, shell=True)
