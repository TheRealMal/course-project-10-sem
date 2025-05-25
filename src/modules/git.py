import os
import shutil
import aiohttp
from git import Repo
from datetime import datetime
from modules.logger import BaseLogger



class Gitlab(BaseLogger):

    __API_PIPELINES = "/projects/{}/pipelines"
    __API_JOBS      = "/projects/{}/pipelines/{}/jobs"

    def __init__(self, host: str, token: str) -> None:
        self.__host     = host
        self.__token    = token

    async def __request_get(self, endpoint: str, body: dict) -> dict | None:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.__host}{endpoint}",
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f"Bearer {self.__token}"
                },
                params=body
            ) as response:
                if response.status != 200:
                    return None
                return await response.json()

    async def get_pipelines(self, project: str, branch: str, page: int = 1) -> list[int] | None:
        pipelines = await self.__request_get(
            self.__API_PIPELINES.format(project),
            {
                "ref":      branch,
                "page":     page,
                "per_page": 100
            }
        )
        if not pipelines:
            return None
        
        if len(pipelines) == 0:
            self._log_err(f"failed to get pipelines for {project}")
            return None
        
        return [pipeline["id"] for pipeline in pipelines]
    
    async def get_jobs(self, project: str, pipe: int, page: int = 1) -> dict | None:
        jobs = await self.__request_get(
            self.__API_JOBS.format(project, pipe),
            {
                "page":     page,
                "per_page": 100
            }
        )
        if not jobs:
            return None
        
        return jobs
    
    def clone_repository(self, repo_url: str, repo_branch: str, dest_path: str) -> bool:
        self.clean_dir(dest_path)
        
        try:
            Repo.clone_from(f"{self.__host.replace('https://', 'https://continuous-monitoring:' + self.__token + '@')}/{repo_url}", dest_path, branch=repo_branch)
            self._log(f"repository cloned successfully: {repo_url} -> {dest_path}")
            return True
        except Exception as e:
            self._log_err(f"failed to clone repository: {e}")
            return False
        
    def clean_dir(self, path: str, project_id: int | None = None) -> None:
        if os.path.exists(path):
            if project_id:
                self._log(f"[{project_id}] cleaning path: {path}")
            else:
                self._log(f"cleaning path: {path}")
            shutil.rmtree(path)
