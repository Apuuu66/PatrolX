"""全局配置（默认轻量、可环境变量覆盖）。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PATROLX_", env_file=".env", extra="ignore")

    base_dir: Path = Path(__file__).resolve().parents[2]
    uploads_dir: Path = Path("uploads")
    output_dir: Path = Path("output")
    config_dir: Path = Path("deploy/config")

    # 上传限制（在线模式）
    max_upload_mb: int = 2048

    # 在线模式元数据库，独立于任务输出目录
    sqlite_path: Path = Path("data/patrolx.db")

    def resolved(self, p: Path) -> Path:
        return p if p.is_absolute() else self.base_dir / p

    @property
    def uploads(self) -> Path:
        return self.resolved(self.uploads_dir)

    @property
    def output(self) -> Path:
        return self.resolved(self.output_dir)

    @property
    def config(self) -> Path:
        return self.resolved(self.config_dir)


settings = Settings()
