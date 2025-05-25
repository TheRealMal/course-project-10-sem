from datetime import datetime
import aiohttp
import os

from modules.logger import BaseLogger


class DefectDojoReport:
    def __init__(
            self, scan_type, endpoint_id, file,
            engagement_id, branch,
            report_name = None
        ):
        self.metadata = aiohttp.FormData()
        self.metadata.add_fields(
            ('minimum_severity', 'Medium'),
            ('active', 'true'),
            ('verified', 'true'),
            ('close_old_findings', 'true'),
            ('close_old_findings_product_scope', 'false'),
            ('push_to_jira', 'false'),
            ('build_id', 'continuous-monitoring'),
            ('commit_hash', 'continuous-monitoring'),
            ('scan_date', datetime.now().strftime("%Y-%m-%d")),
            ('scan_type', scan_type),
            ('endpoint_to_add', str(endpoint_id)),
            ('engagement', str(engagement_id)),
            ('branch_tag', branch)
        )
        self.metadata.add_field('file', file, filename="scan.json")

        if report_name:
            self.metadata.add_fields(
                ('test_title', report_name),
                ('close_old_findings_product_scope', 'false')
            )


class DefectDojo(BaseLogger):
    __API_PRODUCTS      = "/api/v2/products"
    __API_ENGAGEMENTS   = "/api/v2/engagements"
    __API_SCAN          = "/api/v2/import-scan/"
    __API_ENDPOINT      = "/api/v2/endpoints"

    __API_SUCCES_STATUS = set([200, 201])

    __SCANNERS_PREFIXES = set(["trivy"])
    __TARGET_PREFIXES   = set(["prod"])

    def __init__(self, host: str, token: str) -> None:
        self.__host     = host
        self.__token    = f"Token {token}"

    async def __request_get(self, endpoint: str, body: dict) -> dict | None:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.__host}{endpoint}",
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': self.__token
                },
                params=body
            ) as response:
                if response.status != 200:
                    return None
                return await response.json()
            
    async def __request_post(self, endpoint: str, body: dict | None = None, data: dict | aiohttp.formdata.FormData | None = None) -> dict | None:
        if body == None and data == None:
            return None
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.__host}{endpoint}",
                headers={
                    'Authorization': self.__token
                },
                json=body,
                data=data
            ) as response:
                if response.status not in self.__API_SUCCES_STATUS:
                    self._log_err(f"{response.status}:\n{await response.text()}")
                    return None
                return await response.json()

    async def find_product(self, name: str) -> int | None:
        response = await self.__request_get(
            self.__API_PRODUCTS,
            {
                "name": name
            }
        )
        if not response:
            return None
        
        results = response.get("results", [])
        if len(response) == 0:
            self._log_err(f"failed to get product {name}")
            return None
        
        return results[0]["id"]
    
    async def get_product_findings(self, product_id: int) -> list[dict] | None:
        response = await self.__request_get(
            self.__API_PRODUCTS + f"/{product_id}", {}
        )
        if not response:
            return None
        
        return response.get("findings_count", -1)

    async def get_engagement(self, product: int, branch: str | None = None) -> int | None:
        response = await self.__request_get(
            self.__API_ENGAGEMENTS,
            {
                "product": product,
                "branch": branch
            }
        )
        if not response:
            return None
        
        results = response.get("results", [])
        if len(response) == 0:
            self._log_err(f"failed to get engagements for {product}")
            return None
        
        for engagement in results:
            if engagement["branch_tag"] == branch:
                return engagement["id"]
        return None
        
    async def get_engagement_last_update(self, product: int, is_image: bool = False) -> str | None:
        response = await self.__request_get(
            self.__API_ENGAGEMENTS,
            {
                "product": product
            }
        )
        if not response:
            return None
        
        results = response.get("results", [])
        if len(response) == 0:
            self._log_err(f"failed to get engagements for {product}")
            return None
        
        updates = []
        for result in results:
            name_splited = result["name"].split("_")
            if len(name_splited) < 2:
                continue
            if not is_image and (name_splited[1] in self.__SCANNERS_PREFIXES or name_splited[0] not in self.__TARGET_PREFIXES):
                continue
            elif is_image and (name_splited[1] not in self.__SCANNERS_PREFIXES or name_splited[0] not in self.__TARGET_PREFIXES):
                continue

            updates.append((result["updated"]))
        return datetime.strptime(max(updates)[:-8], "%Y-%m-%dT%H:%M:%S").date()

    async def get_images_from_engs(self, product: int) -> list[tuple[int, str, str]] | None:
        response = await self.__request_get(
            self.__API_ENGAGEMENTS,
            {
                "product": product
            }
        )
        if not response:
            return None
        
        results = response.get("results", [])
        if len(response) == 0:
            self._log_err(f"failed to get engagements for {product}")
            return None
        
        images = []
        for result in results:
            name_splited = result["name"].split("_")
            if len(name_splited) < 2:
                continue
            if name_splited[1] not in self.__SCANNERS_PREFIXES:
                continue
            
            images.append((result["id"], "_".join(name_splited[2:]), datetime.strptime(result["updated"][:-8], "%Y-%m-%dT%H:%M:%S").date()))
        return images

    async def get_endpoint_id(self, product_id: int) -> int | None:
        response = await self.__request_get(
            self.__API_ENDPOINT,
            {
                "product": product_id
            }
        )
        if not response:
            return None
        
        results = response.get("results", [])
        if len(results) == 0:
            self._log_err(f"[{product_id}] failed to get endpoint")
            return None
        
        endpoint_id = None
        for endpoint in results:
            if endpoint.get("protocol") is not None:
                endpoint_id = endpoint["id"]
                break

        return endpoint_id
        

    async def send_report(self, report: DefectDojoReport) -> None:
        response = await self.__request_post(
            self.__API_SCAN,
            data = report.metadata
        )
        if not response:
            return None
        
        return response.get("test_id", None)
