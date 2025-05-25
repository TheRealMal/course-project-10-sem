import asyncio
import aiohttp
from datetime import datetime
from modules.logger import BaseLogger
import json

class ScannRunner(BaseLogger):
    __SCANNERS_CONFIG_REPO      = 5425

    __SCANNER_PREFIX_PROJECT    = "PROJECT: "
    __SCANNER_PREFIX_IMAGE      = "IMAGE: "
    __SCANNER_PREFIX_TYPE       = "DD_SCAN_TYPE: "
    __SCANNER_COMMENT_PREFIX    = "#"

    SCANNER_IMAGE_REPORT_NAME_PREFIX = "prod"

    API_FILES_ENDPOINT          = "/api/v4/projects/{}/repository/tree"
    API_FILE_CONTENT_ENDPOINT   = "/api/v4/projects/{}/repository/files/{}/raw"

    CFG_SCAN_CMD    = 0
    CFG_SCAN_TYPE   = 1

    __HARBOR_REGISTRIES = set([
        "registry-dev.ru",
        "registry.ru",
        "harbor.ru",
    ])
    __ANOTHER_REGISTRIES = set([
        "registry.ru",
        "registry.com",
    ])

    def __init__(self, git_host: str, git_token: str, registries_credentials: dict) -> None:
        self.__git_host         = git_host
        self.__git_token        = f"Bearer {git_token}"
        self.__scanners_project = []
        self.__scanners_image   = []
        self.__registries_credentials = registries_credentials

    async def fetch_files_list(self) -> list:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.__git_host}{self.API_FILES_ENDPOINT.format(self.__SCANNERS_CONFIG_REPO)}",
                headers={"Authorization": self.__git_token}
            ) as response:
                return await response.json() if response.status == 200 else []

    async def fetch_file_content(self, file_path: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.__git_host}{self.API_FILE_CONTENT_ENDPOINT.format(self.__SCANNERS_CONFIG_REPO, file_path)}",
                headers={"Authorization": self.__git_token}
            ) as response:
                return await response.text() if response.status == 200 else ""

    async def load_scanners(self):
        files = await self.fetch_files_list()
        for file in files:
            if file["type"] == "blob":
                content = await self.fetch_file_content(file["path"])
                if content == None:
                    continue

                scanner_cfg = content.splitlines()
                if len(scanner_cfg) != 2 or not scanner_cfg[self.CFG_SCAN_TYPE].startswith(self.__SCANNER_PREFIX_TYPE):
                    self._log_err(f"wrong config format: {file['path']}")
                    continue

                if scanner_cfg[self.CFG_SCAN_CMD].startswith(self.__SCANNER_COMMENT_PREFIX):
                    self._log(f"ignoring commented scanner: {file['path']}")
                    continue

                if scanner_cfg[self.CFG_SCAN_CMD].startswith(self.__SCANNER_PREFIX_PROJECT):
                    self.__scanners_project.append((
                        scanner_cfg[self.CFG_SCAN_CMD][len(self.__SCANNER_PREFIX_PROJECT):],
                        scanner_cfg[self.CFG_SCAN_TYPE][len(self.__SCANNER_PREFIX_TYPE):]
                    ))
                elif scanner_cfg[self.CFG_SCAN_CMD].startswith(self.__SCANNER_PREFIX_IMAGE):
                    self.__scanners_image.append((
                        scanner_cfg[0][len(self.__SCANNER_PREFIX_IMAGE):],
                        scanner_cfg[self.CFG_SCAN_TYPE][len(self.__SCANNER_PREFIX_TYPE):]
                    ))
                else:
                    continue

    def get_project_scanners(self):
        return self.__scanners_project
    
    def get_image_scanners(self):
        return self.__scanners_image
    
    async def scan_project(self, project_id: int, path: str, outputs_base_path: str) -> None:
        for scanner_idx in range(len(self.__scanners_project)):
            scan_cmd = self.__scanners_project[scanner_idx][self.CFG_SCAN_CMD].format(PROJECT_PATH=path, OUTPUT_PATH=f"{outputs_base_path}/{scanner_idx}.json")
            result = await self.__execute_command(scan_cmd)
            self._log(f"[{project_id}] {result} {scan_cmd}")
            
    async def scan_image(self, project_id: int, image_url: str, outputs_base_path: str) -> None:
        for scanner_idx in range(len(self.__scanners_image)):
            registry = image_url.split("/")[0]
            registry_credentials = self.__registries_credentials[registry]

            tag = await self.registry_fetch_latest(registry, image_url.replace(f"{registry}/", ""))
            self._log(f"[{project_id}] fetched latest {image_url} tag: {tag}")

            auth_cmd = "docker login {} -u {} -p {}".format(registry, registry_credentials["user"], registry_credentials["password"])
            scan_cmd = self.__scanners_image[scanner_idx][self.CFG_SCAN_CMD].format(IMAGE_URL=f"{image_url}:{tag}", OUTPUT_PATH=f"{outputs_base_path}/{scanner_idx}.json")
            
            result_cmd = f"{auth_cmd} && {scan_cmd}"
            result = await self.__execute_command(result_cmd)
            self._log(f"[{project_id}] {result} {scan_cmd}")
            
    async def __execute_command(self, command: str) -> str | None:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            # self._log(stdout.decode(errors="ignore").strip())
            # self._log_err(stderr.decode(errors="ignore").strip())
            return "\033[31m[failed]\033[0m"
        
        return "\033[92m[success]\033[0m"

    # ------------------------------------------------------------
    # Docker registry
    # ------------------------------------------------------------

    async def registry_fetch_latest(self, registry: str, image: str) -> str:
        tags = await self.__registry_fetch_tags(registry, image)
        if "latest" in tags["tags"]:
            return "latest"
        
        tasks = [self.__registry_fetch_manifest(registry, image, tag) for tag in tags["tags"]]
        results = await asyncio.gather(*tasks)
        results = [result for result in results if result != ""]
        if len(results) == 0:
            return ""
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[0][0]
    
    async def __registry_fetch_tags(self, registry: str, image: str) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://{registry}/v2/{image}/tags/list?page_size=1",
                auth=aiohttp.BasicAuth(
                    self.__registries_credentials[registry]["user"],
                    self.__registries_credentials[registry]["password"]
                )
            ) as response:
                return await response.json() if response.status == 200 else {"tags": []}
    
    async def __registry_fetch_manifest(self, registry: str, image: str, tag: str) -> tuple[str, str]:
        if registry in self.__ANOTHER_REGISTRIES:
            async with aiohttp.ClientSession(auth=aiohttp.BasicAuth(
                    self.__registries_credentials[registry]["user"],
                    self.__registries_credentials[registry]["password"]
                )) as session:
                async with session.get(f"https://{registry}/v2/{image}/manifests/{tag}") as response:
                    if response.status == 200:
                        response_json = await response.json()
                        last_created_manifest = response_json["history"][0]["v1Compatibility"]
                        dictData = json.loads(last_created_manifest)
                        return tag,dictData["created"]
                    else:
                        return tag, ""
        elif registry in self.__HARBOR_REGISTRIES:
            main_repo = image.split('/')[0]
            sub_repo = image[len(main_repo)+1:]
            sub_repo = sub_repo.replace('/', '%2F')
            async with aiohttp.ClientSession(auth=aiohttp.BasicAuth(
                    self.__registries_credentials[registry]["user"],
                    self.__registries_credentials[registry]["password"]
                ), headers={
                    "accept": "application/json"
                }) as session:
                async with session.get(
                    f"https://{registry}/api/v2.0/projects/{main_repo}/repositories/{sub_repo}/artifacts/{tag}/tags",
                    params={
                        "page": 1,
                        "page_size": 10,
                        "with_signature": "false",
                        "with_immutable_status": "false"
                    }
                ) as response:
                    if response.status == 200:
                        response_json = await response.text()
                        response_json = json.loads(response_json)[0]
                        return tag, response_json.get("push_time")
                    else:
                        return tag, ""