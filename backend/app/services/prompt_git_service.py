"""提示词Git版本管理服务。

负责与远程Git仓库（YZ1981-GT/GT_digao）的交互，
包括拉取同步、提交推送、冲突处理和标签管理。
使用 gitpython 库操作本地Git仓库。

Git仓库本地克隆路径：~/.gt_audit_helper/prompt_git/
Git配置存储路径：~/.gt_audit_helper/git_config.json
"""

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Optional

import git
from git.exc import GitCommandError, InvalidGitRepositoryError

from ..models.audit_schemas import (
    GitCommitHistory,
    GitConfig,
    GitConflictInfo,
    GitSyncResult,
)

logger = logging.getLogger(__name__)

# Timeout for remote Git operations (seconds)
GIT_REMOTE_TIMEOUT = 30


class PromptGitService:
    """提示词Git版本管理服务。

    负责与远程Git仓库（YZ1981-GT/GT_digao）的交互，
    包括拉取同步、提交推送、冲突处理和标签管理。
    使用 gitpython 库操作本地Git仓库。

    Git仓库本地克隆路径：~/.gt_audit_helper/prompt_git/
    """

    GIT_REPO_DIR = os.path.join(
        os.path.expanduser("~"), ".gt_audit_helper", "prompt_git"
    )
    CONFIG_PATH = os.path.join(
        os.path.expanduser("~"), ".gt_audit_helper", "git_config.json"
    )

    # TSJ directory – same as PromptLibrary.TSJ_DIR
    TSJ_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "TSJ")

    def __init__(self) -> None:
        self._repo: Optional[git.Repo] = None
        self._config: Optional[GitConfig] = None
        # Attempt to load persisted config on init
        self._load_config()
        # Attempt to open existing repo
        self._try_open_repo()

    # ─── Internal helpers ───

    def _load_config(self) -> None:
        """Load persisted Git config from JSON file."""
        if os.path.isfile(self.CONFIG_PATH):
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = GitConfig(**data)
            except Exception as exc:
                logger.warning("Failed to load git config: %s", exc)
                self._config = None

    def _save_config(self, config: GitConfig) -> None:
        """Persist Git config to JSON file."""
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)
        with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
        self._config = config

    def _try_open_repo(self) -> None:
        """Try to open an existing local Git repo."""
        if os.path.isdir(os.path.join(self.GIT_REPO_DIR, ".git")):
            try:
                self._repo = git.Repo(self.GIT_REPO_DIR)
            except InvalidGitRepositoryError:
                self._repo = None

    def _ensure_configured(self) -> Optional[str]:
        """Return an error message if Git is not configured, else None."""
        if self._config is None:
            return "Git仓库尚未配置，请先调用 configure() 配置仓库信息"
        return None

    def _ensure_repo(self) -> Optional[str]:
        """Return an error message if repo is not available, else None."""
        err = self._ensure_configured()
        if err:
            return err
        if self._repo is None:
            return "本地Git仓库不存在，请先调用 configure() 克隆仓库"
        return None

    def _build_clone_url(self, config: GitConfig) -> str:
        """Build the clone URL with embedded token for HTTPS repos."""
        url = config.repo_url
        if config.auth_type == "token" and config.auth_credential:
            # Embed token into HTTPS URL: https://<token>@host/path
            if url.startswith("https://"):
                url = url.replace("https://", f"https://{config.auth_credential}@", 1)
            elif url.startswith("http://"):
                url = url.replace("http://", f"http://{config.auth_credential}@", 1)
        return url

    def _get_git_env(self) -> Dict[str, str]:
        """Build environment dict for SSH-based auth."""
        env: Dict[str, str] = {}
        if self._config and self._config.auth_type == "ssh_key" and self._config.auth_credential:
            ssh_key_path = self._config.auth_credential
            env["GIT_SSH_COMMAND"] = f'ssh -i "{ssh_key_path}" -o StrictHostKeyChecking=no'
        return env

    def _sync_to_tsj(self) -> List[str]:
        """Copy markdown files from the git repo to the local TSJ directory.

        Returns list of updated file names.
        """
        updated: List[str] = []
        if self._repo is None:
            return updated

        tsj_dir = os.path.normpath(self.TSJ_DIR)
        os.makedirs(tsj_dir, exist_ok=True)

        repo_dir = self.GIT_REPO_DIR
        for fname in os.listdir(repo_dir):
            if fname.startswith("."):
                continue
            src = os.path.join(repo_dir, fname)
            if os.path.isfile(src) and fname.lower().endswith(".md"):
                dst = os.path.join(tsj_dir, fname)
                shutil.copy2(src, dst)
                updated.append(fname)

        return updated

    # ─── Public API ───

    def configure(self, config: GitConfig) -> GitSyncResult:
        """配置Git仓库关联：URL、认证凭据（SSH密钥或Token）和目标分支。

        若本地仓库不存在则执行 git clone，否则更新 remote URL。
        """
        try:
            clone_url = self._build_clone_url(config)
            env = {}
            if config.auth_type == "ssh_key" and config.auth_credential:
                env["GIT_SSH_COMMAND"] = (
                    f'ssh -i "{config.auth_credential}" -o StrictHostKeyChecking=no'
                )

            if os.path.isdir(os.path.join(self.GIT_REPO_DIR, ".git")):
                # Repo already exists – update remote URL and fetch
                repo = git.Repo(self.GIT_REPO_DIR)
                origin = repo.remotes.origin
                with origin.config_writer as cw:
                    cw.set("url", clone_url)
                origin.fetch(kill_after_timeout=GIT_REMOTE_TIMEOUT, env=env)
                self._repo = repo
            else:
                # Clone fresh
                os.makedirs(self.GIT_REPO_DIR, exist_ok=True)
                repo = git.Repo.clone_from(
                    clone_url,
                    self.GIT_REPO_DIR,
                    branch=config.branch,
                    kill_after_timeout=GIT_REMOTE_TIMEOUT,
                    env=env,
                )
                self._repo = repo

            # Checkout target branch
            if config.branch and config.branch != str(repo.active_branch):
                if config.branch in [ref.name for ref in repo.branches]:
                    repo.heads[config.branch].checkout()
                else:
                    # Create tracking branch from remote
                    repo.git.checkout("-b", config.branch, f"origin/{config.branch}")

            self._save_config(config)
            return GitSyncResult(
                success=True,
                message=f"Git仓库配置成功，分支: {config.branch}",
            )

        except GitCommandError as exc:
            error_msg = str(exc)
            if "Authentication failed" in error_msg or "Permission denied" in error_msg:
                return GitSyncResult(
                    success=False,
                    message="Git认证失败，请检查凭据是否正确",
                )
            if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                return GitSyncResult(
                    success=False,
                    message="Git仓库连接超时（30秒），请检查网络或仓库地址",
                )
            return GitSyncResult(success=False, message=f"Git配置失败: {error_msg}")
        except Exception as exc:
            return GitSyncResult(success=False, message=f"Git配置失败: {exc}")

    def get_config(self) -> Optional[GitConfig]:
        """获取当前Git仓库配置。"""
        return self._config

    def pull_latest(self) -> GitSyncResult:
        """从远程Git仓库拉取最新提示词文件，更新本地TSJ目录。"""
        err = self._ensure_repo()
        if err:
            return GitSyncResult(success=False, message=err)

        assert self._repo is not None
        assert self._config is not None

        try:
            env = self._get_git_env()
            origin = self._repo.remotes.origin

            # Fetch first to detect changes
            fetch_info = origin.fetch(
                kill_after_timeout=GIT_REMOTE_TIMEOUT, env=env
            )

            # Record files before pull
            before_files = set()
            for item in self._repo.tree().traverse():
                if hasattr(item, "path"):
                    before_files.add(item.path)

            # Pull
            origin.pull(
                self._config.branch,
                kill_after_timeout=GIT_REMOTE_TIMEOUT,
                env=env,
            )

            # Record files after pull
            after_files = set()
            for item in self._repo.tree().traverse():
                if hasattr(item, "path"):
                    after_files.add(item.path)

            added = list(after_files - before_files)
            deleted = list(before_files - after_files)

            # Sync markdown files to TSJ directory
            updated = self._sync_to_tsj()

            return GitSyncResult(
                success=True,
                message="拉取同步成功",
                added_files=added,
                updated_files=updated,
                deleted_files=deleted,
            )

        except GitCommandError as exc:
            error_msg = str(exc)
            if "Authentication failed" in error_msg or "Permission denied" in error_msg:
                return GitSyncResult(
                    success=False,
                    message="Git认证失败，请检查凭据是否正确",
                )
            if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                return GitSyncResult(
                    success=False,
                    message="Git仓库连接超时（30秒），请检查网络或仓库地址",
                )
            # Merge conflicts
            if "conflict" in error_msg.lower() or "CONFLICT" in error_msg:
                conflicts = self._detect_conflict_files()
                return GitSyncResult(
                    success=False,
                    message="拉取时存在冲突，请解决冲突后重试",
                    has_conflicts=True,
                    conflicts=conflicts,
                )
            return GitSyncResult(success=False, message=f"拉取失败: {error_msg}")
        except Exception as exc:
            return GitSyncResult(success=False, message=f"拉取失败: {exc}")

    def commit_and_push(
        self,
        changed_files: List[str],
        change_type: str,
        prompt_name: str,
        operator: str,
    ) -> GitSyncResult:
        """将本地变更提交到远程Git仓库。

        提交信息格式：[{change_type}] {prompt_name} - by {operator}
        change_type: modify/replace/append
        """
        err = self._ensure_repo()
        if err:
            return GitSyncResult(success=False, message=err)

        assert self._repo is not None
        assert self._config is not None

        try:
            # Stage changed files
            if changed_files:
                self._repo.index.add(changed_files)
            else:
                # Stage all changes
                self._repo.git.add(A=True)

            # Build commit message
            commit_message = f"[{change_type}] {prompt_name} - by {operator}"
            self._repo.index.commit(commit_message)

            # Push
            env = self._get_git_env()
            origin = self._repo.remotes.origin
            push_info = origin.push(
                self._config.branch,
                kill_after_timeout=GIT_REMOTE_TIMEOUT,
                env=env,
            )

            # Check push result for errors
            for info in push_info:
                if info.flags & info.ERROR:
                    return GitSyncResult(
                        success=False,
                        message=f"推送失败: {info.summary}",
                    )
                if info.flags & info.REJECTED or info.flags & info.REMOTE_REJECTED:
                    return GitSyncResult(
                        success=False,
                        message="推送被拒绝：远程仓库有更新，请先拉取最新版本再推送（409冲突）",
                    )

            return GitSyncResult(
                success=True,
                message=f"提交并推送成功: {commit_message}",
                updated_files=changed_files,
            )

        except GitCommandError as exc:
            error_msg = str(exc)
            if "Authentication failed" in error_msg or "Permission denied" in error_msg:
                return GitSyncResult(
                    success=False,
                    message="Git认证失败，请检查凭据是否正确",
                )
            if "rejected" in error_msg.lower() or "non-fast-forward" in error_msg.lower():
                return GitSyncResult(
                    success=False,
                    message="推送被拒绝：远程仓库有更新，请先拉取最新版本再推送（409冲突）",
                )
            if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
                return GitSyncResult(
                    success=False,
                    message="Git仓库连接超时（30秒），请检查网络或仓库地址",
                )
            return GitSyncResult(success=False, message=f"推送失败: {error_msg}")
        except Exception as exc:
            return GitSyncResult(success=False, message=f"推送失败: {exc}")

    def get_commit_history(
        self, file_path: Optional[str] = None, limit: int = 50
    ) -> List[GitCommitHistory]:
        """获取提示词的Git版本历史。

        若指定 file_path，返回该文件的提交历史；否则返回全部提交历史。
        """
        err = self._ensure_repo()
        if err:
            return []

        assert self._repo is not None

        try:
            if file_path:
                commits = list(self._repo.iter_commits(paths=file_path, max_count=limit))
            else:
                commits = list(self._repo.iter_commits(max_count=limit))

            history: List[GitCommitHistory] = []
            for c in commits:
                # Get changed files for this commit
                changed: List[str] = []
                if c.parents:
                    diff = c.parents[0].diff(c)
                    changed = [d.a_path or d.b_path for d in diff if d.a_path or d.b_path]

                history.append(
                    GitCommitHistory(
                        commit_hash=c.hexsha,
                        message=c.message.strip(),
                        author=str(c.author),
                        committed_at=datetime.fromtimestamp(
                            c.committed_date, tz=timezone.utc
                        ).isoformat(),
                        changed_files=changed,
                    )
                )
            return history

        except Exception as exc:
            logger.error("Failed to get commit history: %s", exc)
            return []

    def _detect_conflict_files(self) -> List[str]:
        """Internal helper to list files with merge conflicts."""
        if self._repo is None:
            return []
        try:
            unmerged = self._repo.index.unmerged_blobs()
            return list(unmerged.keys())
        except Exception:
            return []

    def detect_conflicts(self) -> List[GitConflictInfo]:
        """检测本地与远程的冲突文件列表。"""
        err = self._ensure_repo()
        if err:
            return []

        assert self._repo is not None

        try:
            unmerged = self._repo.index.unmerged_blobs()
            conflicts: List[GitConflictInfo] = []

            for file_path, blob_list in unmerged.items():
                local_content = ""
                remote_content = ""
                base_content = None

                for stage, blob in blob_list:
                    content = blob.data_stream.read().decode("utf-8", errors="replace")
                    if stage == 1:
                        # Common ancestor
                        base_content = content
                    elif stage == 2:
                        # Ours (local)
                        local_content = content
                    elif stage == 3:
                        # Theirs (remote)
                        remote_content = content

                conflicts.append(
                    GitConflictInfo(
                        file_path=file_path,
                        local_content=local_content,
                        remote_content=remote_content,
                        base_content=base_content,
                    )
                )

            return conflicts

        except Exception as exc:
            logger.error("Failed to detect conflicts: %s", exc)
            return []

    def resolve_conflict(
        self,
        file_path: str,
        resolution: str,
        merged_content: Optional[str] = None,
    ) -> GitSyncResult:
        """解决冲突。

        resolution: 'keep_local' | 'use_remote' | 'manual_merge'
        manual_merge 时需提供 merged_content。
        """
        err = self._ensure_repo()
        if err:
            return GitSyncResult(success=False, message=err)

        assert self._repo is not None

        try:
            full_path = os.path.join(self.GIT_REPO_DIR, file_path)

            if resolution == "keep_local":
                # Use ours: checkout --ours
                self._repo.git.checkout("--ours", file_path)
            elif resolution == "use_remote":
                # Use theirs: checkout --theirs
                self._repo.git.checkout("--theirs", file_path)
            elif resolution == "manual_merge":
                if merged_content is None:
                    return GitSyncResult(
                        success=False,
                        message="手动合并需要提供 merged_content",
                    )
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(merged_content)
            else:
                return GitSyncResult(
                    success=False,
                    message=f"不支持的解决方式: {resolution}",
                )

            # Stage the resolved file
            self._repo.index.add([file_path])

            return GitSyncResult(
                success=True,
                message=f"冲突已解决: {file_path} ({resolution})",
                updated_files=[file_path],
            )

        except Exception as exc:
            return GitSyncResult(
                success=False,
                message=f"解决冲突失败: {exc}",
            )

    def create_tag(self, tag_name: str, message: str = "") -> GitSyncResult:
        """创建Git标签（版本快照）。"""
        err = self._ensure_repo()
        if err:
            return GitSyncResult(success=False, message=err)

        assert self._repo is not None

        try:
            # Check for duplicate tag name
            existing_tags = [t.name for t in self._repo.tags]
            if tag_name in existing_tags:
                return GitSyncResult(
                    success=False,
                    message=f"标签 '{tag_name}' 已存在",
                )

            self._repo.create_tag(tag_name, message=message or tag_name)

            # Push tag to remote
            env = self._get_git_env()
            origin = self._repo.remotes.origin
            origin.push(tag_name, kill_after_timeout=GIT_REMOTE_TIMEOUT, env=env)

            return GitSyncResult(
                success=True,
                message=f"标签 '{tag_name}' 创建成功",
            )

        except GitCommandError as exc:
            error_msg = str(exc)
            if "already exists" in error_msg:
                return GitSyncResult(
                    success=False,
                    message=f"标签 '{tag_name}' 已存在",
                )
            return GitSyncResult(
                success=False,
                message=f"创建标签失败: {error_msg}",
            )
        except Exception as exc:
            return GitSyncResult(
                success=False,
                message=f"创建标签失败: {exc}",
            )

    def list_tags(self) -> List[Dict[str, str]]:
        """列出所有Git标签。"""
        err = self._ensure_repo()
        if err:
            return []

        assert self._repo is not None

        try:
            tags: List[Dict[str, str]] = []
            for tag in self._repo.tags:
                tag_info: Dict[str, str] = {
                    "name": tag.name,
                    "commit": str(tag.commit),
                }
                # Annotated tags have a tag object with a message
                if tag.tag is not None:
                    tag_info["message"] = tag.tag.message.strip() if tag.tag.message else ""
                    tag_info["tagger"] = str(tag.tag.tagger) if tag.tag.tagger else ""
                    if tag.tag.tagged_date:
                        tag_info["created_at"] = datetime.fromtimestamp(
                            tag.tag.tagged_date, tz=timezone.utc
                        ).isoformat()
                else:
                    tag_info["message"] = ""
                tags.append(tag_info)
            return tags

        except Exception as exc:
            logger.error("Failed to list tags: %s", exc)
            return []
