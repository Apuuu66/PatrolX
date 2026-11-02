"""任务最终可巡检文件的执行期内存清单。"""

from dataclasses import dataclass
from pathlib import Path

from app.services.extraction.manifest import ManifestV5Error, read_manifest, sha256_file
from app.services.scanning.matcher import match_paths


@dataclass(frozen=True, slots=True)
class TaskFileCatalog:
    """任务现场只读文件清单；只信任 manifest v5 的 catalog。"""

    root: Path
    _paths: tuple[Path, ...]

    @classmethod
    def build(cls, data_dir: Path) -> "TaskFileCatalog":
        """从已发布 manifest v5 构建 catalog，不回退扫描分类目录。"""
        if data_dir.is_symlink():
            raise ManifestV5Error(f"任务目录不得是链接: {data_dir}")
        root = data_dir.resolve()
        manifest = read_manifest(root)
        collected: list[Path] = []
        for item in manifest["catalog"]:
            relative = Path(item["path"])
            cls._validate_regular_file_chain(root, relative)
            path = root / relative
            if not path.is_file():
                raise ManifestV5Error(f"catalog 条目不是普通文件: {relative.as_posix()}")
            try:
                size = path.stat().st_size
                digest = sha256_file(path)
            except OSError as exc:
                raise ManifestV5Error(f"无法读取 catalog 文件: {relative.as_posix()}") from exc
            if size != item["size"] or digest != item["sha256"]:
                raise ManifestV5Error(f"catalog 文件摘要或大小不一致: {relative.as_posix()}")
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ManifestV5Error(f"catalog 路径越界: {relative.as_posix()}")
            collected.append(relative)
        return cls(root=root, _paths=tuple(collected))

    @staticmethod
    def _validate_regular_file_chain(root: Path, relative: Path) -> None:
        """拒绝 catalog 路径任一段为链接，避免 manifest 之外的现场泄漏。"""
        if relative.is_absolute() or ".." in relative.parts:
            raise ManifestV5Error(f"catalog 路径越界: {relative.as_posix()}")
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ManifestV5Error(f"catalog 路径包含链接: {relative.as_posix()}")

    def paths(self) -> list[Path]:
        """返回稳定排序的相对路径副本。"""
        return list(self._paths)

    def match(self, source_patterns: list[str]) -> list[Path]:
        """按规则声明执行 `re.fullmatch()` 并返回稳定排序匹配集。"""
        return match_paths(list(self._paths), source_patterns)

    def resolve(self, relative: Path) -> Path:
        """将相对路径解析到任务根内；拒绝越界或未发布路径。"""
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"匹配路径越界: {relative.as_posix()}")
        if relative not in self._paths:
            raise ValueError(f"路径不在任务文件清单中: {relative.as_posix()}")
        self._validate_regular_file_chain(self.root, relative)
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"匹配路径越界: {relative.as_posix()}")
        return resolved
