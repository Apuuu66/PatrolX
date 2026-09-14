"""任务最终可巡检文件的执行期内存清单。"""

import os
from dataclasses import dataclass
from pathlib import Path

from app.services.extraction.layout import WORK_CATEGORIES
from app.services.scanning.matcher import match_paths


@dataclass(frozen=True, slots=True)
class TaskFileCatalog:
    """任务现场只读文件清单；不持久化，也不复制文件。"""

    root: Path
    _paths: tuple[Path, ...]

    @classmethod
    def build(cls, data_dir: Path) -> "TaskFileCatalog":
        """构建一次最终可巡检文件清单。"""
        root = data_dir.resolve()
        collected: set[Path] = set()
        for category in WORK_CATEGORIES:
            category_root = root / category
            if not category_root.exists():
                continue
            if category_root.is_symlink() or not category_root.is_dir():
                raise ValueError(f"分类目录不是合法目录: {category_root}")
            for current, directories, files in os.walk(category_root, followlinks=False):
                current_path = Path(current)
                for name in directories:
                    directory = current_path / name
                    if directory.is_symlink():
                        raise ValueError(f"目录链接被拒绝: {directory}")
                for name in files:
                    path = current_path / name
                    if path.is_symlink():
                        raise ValueError(f"文件链接被拒绝: {path}")
                    if not path.is_file():
                        continue
                    relative = path.relative_to(root)
                    resolved = path.resolve()
                    if not resolved.is_relative_to(root) or ".." in relative.parts:
                        raise ValueError(f"匹配路径越界: {relative.as_posix()}")
                    collected.add(relative)
        paths = tuple(sorted(collected, key=lambda path: path.as_posix()))
        return cls(root=root, _paths=paths)

    def paths(self) -> list[Path]:
        """返回稳定排序的相对路径副本。"""
        return list(self._paths)

    def match(self, source_patterns: list[str]) -> list[Path]:
        """按规则声明执行 `re.fullmatch()` 并返回稳定排序匹配集。"""
        return match_paths(list(self._paths), source_patterns)

    def resolve(self, relative: Path) -> Path:
        """将相对路径解析到任务根内；拒绝越界路径。"""
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"匹配路径越界: {relative.as_posix()}")
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"匹配路径越界: {relative.as_posix()}")
        if relative not in self._paths:
            raise ValueError(f"路径不在任务文件清单中: {relative.as_posix()}")
        return resolved
