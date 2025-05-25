from datetime import datetime, timedelta
import asyncio
import json
import os

from dotenv import load_dotenv
load_dotenv()

from modules.logger import BaseLogger
from modules.config import ProjectConfig
from modules.db import Database
from modules.defectdojo import DefectDojo, DefectDojoReport
from modules.git import Gitlab
from modules.scanner import ScannRunner
from modules.rocket import Rocket

from modules.db import Tables, ProjectColumns, ImageColumns, DastColumns

MESSAGE_PROJECT_REPORT = """:small_blue_diamond: {team}

:warning: Continous monitoring found {findings_count} vulnerabilities
– DefectDojo: https://defectdojo.ru/product/{project_id}
– Gitlab: https://git.ru/{gitlab_url}
– Branch: {gitlab_branch}
"""

MESSAGE_IMAGE_REPORT = """:small_blue_diamond: {team}

:warning: Continous monitoring found {findings_count} vulnerabilities
– Image: {image_url}
– DefectDojo: https://defectdojo.ru/engagement/{engagement_id}
– Gitlab: https://git.ru/{gitlab_url}
– Branch: {gitlab_branch}
"""

class Main(BaseLogger):

    __BASE_TMP_PATH = "./.tmp"

    def __init__(self, dd: DefectDojo, gitlab: Gitlab, scanner: ScannRunner, db: Database, rocket: Rocket) -> None:
        self.dd         = dd
        self.gitlab     = gitlab
        self.scanner    = scanner
        self.db         = db
        self.rocket     = rocket

    async def sync_projects_with_db(self, projects: list[ProjectConfig]) -> None:
        for project in projects:
            db_project = await self.db.fetch_row(
                Tables.PROJECTS,
                ProjectColumns.GITLAB_URL,
                project.gitlab_url
            )
            if not db_project:
                self._log(f"adding new project {project.gitlab_url}")
                await self.__add_new_project(project)
                continue
            self._log(f"syncing existing project {project.gitlab_url}")
            await self.__sync_single_project(db_project)

    async def __sync_single_project(self, db_project: dict) -> None:
        last_scan_at = await self.dd.get_engagement_last_update(db_project[ProjectColumns.DD_PROJECT_ID.value])
        if last_scan_at > db_project[ProjectColumns.LAST_SCAN_AT.value]:
            self._log(f"[{db_project[ProjectColumns.DD_PROJECT_ID.value]}] updating last_scan_at")
            await self.db.update_row(
                Tables.PROJECTS,
                ProjectColumns.ID,
                db_project[ProjectColumns.ID.value],
                ProjectColumns.LAST_SCAN_AT,
                last_scan_at
            )

        self._log(f"[{db_project[ProjectColumns.DD_PROJECT_ID.value]}] getting dd images")
        dd_images = await self.dd.get_images_from_engs(
            db_project[ProjectColumns.DD_PROJECT_ID.value]
        )
        self._log(f"[{db_project[ProjectColumns.DD_PROJECT_ID.value]}] getting db images")
        db_images = await self.db.fetch_rows(
            Tables.IMAGES,
            ImageColumns.PROJECT_ID,
            db_project[ProjectColumns.DD_PROJECT_ID.value]
        )
        if dd_images == None or db_images == None:
            self._log_err(f"[{db_project[ProjectColumns.DD_PROJECT_ID.value]}] failed to get dd_images or db_images\n           dd_images: {dd_images}\n           db_images: {db_images}")
            return

        self._log(f"[{db_project[ProjectColumns.DD_PROJECT_ID.value]}] syncing dd & db images")
        await self.__sync_images(
            db_project[ProjectColumns.DD_PROJECT_ID.value],
            dd_images,
            db_images
        )
    
    async def __sync_images(self, project_id: str, dd_images: list[tuple[int, str]], db_images: list[dict]) -> None:
        set_dd_images, set_db_images = set([dd_image[0] for dd_image in dd_images]), set([db_image[ImageColumns.ENGAGEMENT_ID.value] for db_image in db_images])
        sets_intersection = set_dd_images & set_db_images
        old_images, new_images = None, None

        # same images in db & dd
        if set_dd_images == set_db_images: 
            return
        # dd has more images -> append new
        elif sets_intersection == set_db_images:
            new_images = set_dd_images - set_db_images
        # db has more images -> delete old
        elif sets_intersection == set_dd_images:
            old_images = set_db_images - set_dd_images
        # absolutely different sets
        elif len(sets_intersection) == 0:
            old_images = set_db_images
            new_images = set_dd_images
        # both new and old images
        else:
            old_images = set_db_images - sets_intersection
            new_images = set_dd_images - sets_intersection

        if old_images:
            self._log(f"[{project_id}] removing old images from db: {old_images}")
            await self.db.delete_rows(
                Tables.IMAGES,
                ImageColumns.ENGAGEMENT_ID,
                [str(image_id) for image_id in old_images]
            )
        
        if new_images:
            self._log(f"[{project_id}] appending new images to db: {new_images}")
            for dd_image in dd_images:
                if dd_image[0] not in new_images:
                    continue
                await self.db.insert_row(
                    Tables.IMAGES,
                    {
                        ImageColumns.ENGAGEMENT_ID: dd_image[0],
                        ImageColumns.IMAGE_URL:     dd_image[1],
                        ImageColumns.IS_ACTIVE:     True,
                        ImageColumns.LAST_SCAN_AT:  dd_image[2],
                        ImageColumns.PROJECT_ID:    project_id
                    }
                )

        for dd_image in dd_images:
            if dd_image[0] not in sets_intersection:
                continue
            db_image = next(db_image for db_image in db_images if db_image[ImageColumns.ENGAGEMENT_ID.value] == dd_image[0])
            if dd_image[2] < db_image[ImageColumns.LAST_SCAN_AT.value]:
                continue

            self._log(f"[{db_image[ImageColumns.IMAGE_URL.value]}] updating last_scan_at")
            await self.db.update_row(
                Tables.IMAGES,
                ImageColumns.ID,
                db_image[ImageColumns.ID.value],
                ImageColumns.LAST_SCAN_AT,
                dd_image[2]
            )
        
    async def __add_new_project(self, project: ProjectConfig) -> None:
        dd_project_id = await self.dd.find_product(project.gitlab_url)
        if not dd_project_id:
            self._log_err(f"failed to get dd product {project.gitlab_url}")
            return
        
        last_scan_at = await self.dd.get_engagement_last_update(dd_project_id)

        await self.db.insert_row(
            Tables.PROJECTS,
            {
                ProjectColumns.IS_ACTIVE:       True,
                ProjectColumns.GITLAB_URL:      project.gitlab_url,
                ProjectColumns.GITLAB_BRANCH:   project.gitlab_branch,
                ProjectColumns.DD_PROJECT_ID:   dd_project_id,
                ProjectColumns.LAST_SCAN_AT:    last_scan_at,
                ProjectColumns.TEAM:            project.team
            }
        )
        dd_images = await self.dd.get_images_from_engs(dd_project_id)
        if not dd_images:
            self._log_err(f"[{dd_project_id}] failed to get dd images")
            return

        for dd_image in dd_images:
            self._log(f"[{dd_project_id}] adding new image to db: {dd_image[1]}")
            await self.db.insert_row(
                Tables.IMAGES,
                {
                    ImageColumns.ENGAGEMENT_ID: dd_image[0],
                    ImageColumns.IMAGE_URL:     dd_image[1],
                    ImageColumns.IS_ACTIVE:     True,
                    ImageColumns.LAST_SCAN_AT:  dd_image[2],
                    ImageColumns.PROJECT_ID:    dd_project_id
                }
            )

    async def process_projects_from_db(self) -> None:
        offset, limit = 0, 5
        while True:
            projects = await self.db.fetch_rows_page(
                Tables.PROJECTS,
                offset,
                limit
            )
            if projects == None:
                self._log_err(f"failed to get projects (offest = {offset}, limit = {limit})")
                continue
            
            if len(projects) == 0:
                break

            tasks = [self.__process_project(project) for project in projects]
            await asyncio.gather(*tasks)
            offset += limit
    
    async def __process_project(self, project: dict) -> None:
        self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] processing")

        if project[ProjectColumns.IS_ACTIVE.value] == False:
            self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] skipping (project is not active)")
            return
        
        last_scan_delta = datetime.now().date() - project[ProjectColumns.LAST_SCAN_AT.value]
        delta_limit = timedelta(days=0)
        if last_scan_delta < delta_limit:
            self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] skipping (time delta is {last_scan_delta})")
            return
        
        self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] cloning repository")
        project_path = f"{self.__BASE_TMP_PATH}/project/{project[ProjectColumns.DD_PROJECT_ID.value]}/"
        if not self.gitlab.clone_repository(project[ProjectColumns.GITLAB_URL.value], project[ProjectColumns.GITLAB_BRANCH.value], project_path):
            self._log_err(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] failed to clone")
            return
        
        reports_dir = f"{self.__BASE_TMP_PATH}/reports/{project[ProjectColumns.DD_PROJECT_ID.value]}"
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)
        
        self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] scaning...")
        await self.scanner.scan_project(project[ProjectColumns.DD_PROJECT_ID.value], project_path, reports_dir)
        self.gitlab.clean_dir(project_path, project[ProjectColumns.DD_PROJECT_ID.value])

        if len(os.listdir(reports_dir)) == 0:
            self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] no reports to upload")
            return
        
        self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] uploading reports...")
        await self.__send_project_reports(project, reports_dir)
        self.gitlab.clean_dir(reports_dir, project[ProjectColumns.DD_PROJECT_ID.value])

        self._log(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] updating last_scan_at")
        await self.db.update_row(
            Tables.PROJECTS,
            ProjectColumns.ID,
            project[ProjectColumns.ID.value],
            ProjectColumns.LAST_SCAN_AT,
            datetime.now().date()
        )

        findings_count = await self.dd.get_product_findings(project[ProjectColumns.DD_PROJECT_ID.value])
        if findings_count == None or findings_count == -1:
            self._log_err(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] failed to get findings count")
            return
        elif findings_count == 0:
            return
        
        
        self.rocket.send_message(
            MESSAGE_PROJECT_REPORT.format(
                team=project[ProjectColumns.TEAM.value],
                findings_count=findings_count,
                project_id=project[ProjectColumns.DD_PROJECT_ID.value],
                gitlab_url=project[ProjectColumns.GITLAB_URL.value],
                gitlab_branch=project[ProjectColumns.GITLAB_BRANCH.value]
            )
        )
        
    async def __send_project_reports(self, project: dict, reports_dir: str) -> None:
        endpoint_id = await self.dd.get_endpoint_id(project[ProjectColumns.DD_PROJECT_ID.value])
        engagement_id = await self.dd.get_engagement(
            project[ProjectColumns.DD_PROJECT_ID.value],
            project[ProjectColumns.GITLAB_BRANCH.value]
        )

        if not all([endpoint_id, engagement_id]):
            self._log_err(f"[{project[ProjectColumns.DD_PROJECT_ID.value]}] failed to send project reports: endpoint = {endpoint_id}, eng = {engagement_id}")
            return
        
        scanners = self.scanner.get_project_scanners()

        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)
        reports = [f for f in os.listdir(reports_dir) if os.path.isfile(os.path.join(reports_dir, f))]

        tasks = []
        for report in reports:
            scanner_idx = int(report.replace(".json", ""))
            scanner = scanners[scanner_idx]
            tasks.append(
                self.__send_report(
                    project_id = project[ProjectColumns.DD_PROJECT_ID.value],
                    file_path = os.path.join(reports_dir, report),
                    scan_type = scanner[self.scanner.CFG_SCAN_TYPE],
                    engagement_id = engagement_id,
                    endpoint_id = endpoint_id,
                    branch = project[ProjectColumns.GITLAB_BRANCH.value],
                    report_name = None
                )
            )

        await asyncio.gather(*tasks)

    async def process_images_from_db(self) -> None:
        offset, limit = 0, 5
        while True:
            images = await self.db.fetch_rows_page(
                Tables.IMAGES,
                offset,
                limit
            )
            if images == None:
                self._log_err(f"failed to get images (offset = {offset}, limit = {limit})")
                continue
            
            if len(images) == 0:
                break

            tasks = [self.__process_image(image) for image in images]
            await asyncio.gather(*tasks)
            offset += limit

    async def __process_image(self, image: dict) -> None:
        self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] processing image {image[ImageColumns.IMAGE_URL.value]}")

        if image[ImageColumns.IS_ACTIVE.value] == False:
            self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] skipping (image is not active)")
            return

        last_scan_delta = datetime.now().date() - image[ImageColumns.LAST_SCAN_AT.value]
        delta_limit = timedelta(days=0)
        if last_scan_delta < delta_limit:
            self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] skipping image [{image[ImageColumns.IMAGE_URL.value]}] (time delta is {last_scan_delta})")
            return

        reports_dir = f"{self.__BASE_TMP_PATH}/reports/{image[ImageColumns.PROJECT_ID.value]}_{image[ImageColumns.ENGAGEMENT_ID.value]}"
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)
        
        self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] scanning image...")
        await self.scanner.scan_image(image[ImageColumns.PROJECT_ID.value], image[ImageColumns.IMAGE_URL.value], reports_dir)

        if len(os.listdir(reports_dir)) == 0:
            self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] no reports to upload for {image[ImageColumns.IMAGE_URL.value]}")
            return

        self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] uploading image reports...")
        await self.__send_image_reports(image, reports_dir)
        self.gitlab.clean_dir(reports_dir, image[ImageColumns.PROJECT_ID.value])

        self._log(f"[{image[ImageColumns.PROJECT_ID.value]}] updating last_scan_at")
        await self.db.update_row(
            Tables.IMAGES,
            ImageColumns.ID,
            image[ImageColumns.ID.value],
            ImageColumns.LAST_SCAN_AT,
            datetime.now().date()
        )

        findings_count = await self.dd.get_product_findings(image[ImageColumns.PROJECT_ID.value])
        if findings_count == None or findings_count == -1:
            self._log_err(f"[{image[ImageColumns.PROJECT_ID.value]}] failed to get findings count")
            return
        elif findings_count == 0:
            return
        
        dd_project = await self.db.fetch_row(
            Tables.PROJECTS,
            ProjectColumns.DD_PROJECT_ID,
            image[ImageColumns.PROJECT_ID.value]
        )
        if not dd_project:
            self._log_err(f"[{image[ImageColumns.PROJECT_ID.value]}] failed to get dd project")
            return
        
        self.rocket.send_message(
            MESSAGE_IMAGE_REPORT.format(
                team=dd_project[ProjectColumns.TEAM.value],
                findings_count=findings_count,
                image_url=image[ImageColumns.IMAGE_URL.value],
                engagement_id=image[ImageColumns.ENGAGEMENT_ID.value],
                gitlab_url=dd_project[ProjectColumns.GITLAB_URL.value],
                gitlab_branch=dd_project[ProjectColumns.GITLAB_BRANCH.value]
            )
        )

    async def __send_image_reports(self, image: dict, reports_dir: str) -> None:
        endpoint_id = await self.dd.get_endpoint_id(image[ImageColumns.PROJECT_ID.value])
        if not endpoint_id:
            self._log_err(f"[{image[ImageColumns.PROJECT_ID.value]}] failed to send image reports: endpoint = {endpoint_id}")
            return
        
        scanners = self.scanner.get_image_scanners()

        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)
        reports = [f for f in os.listdir(reports_dir) if os.path.isfile(os.path.join(reports_dir, f))]

        tasks = []
        for report in reports:
            scanner_idx = int(report.replace(".json", ""))
            scanner = scanners[scanner_idx]
            tasks.append(
                self.__send_report(
                    project_id = image[ImageColumns.PROJECT_ID.value],
                    file_path = os.path.join(reports_dir, report),
                    scan_type = scanner[self.scanner.CFG_SCAN_TYPE],
                    engagement_id = image[ImageColumns.ENGAGEMENT_ID.value],
                    endpoint_id = endpoint_id,
                    branch = "continouous-monitoring-images",
                    report_name = f"{self.scanner.SCANNER_IMAGE_REPORT_NAME_PREFIX}_trivy_{image[ImageColumns.ENGAGEMENT_ID.value]}"
                )
            )
        await asyncio.gather(*tasks)

    async def __send_report(self, project_id: int, file_path: str, scan_type: str,
                            engagement_id: int | None = None, endpoint_id: int | None = None,
                            branch: str | None = None, report_name: str | None = None) -> int | None:
        if not os.path.exists(file_path):
            return None

        with open(file_path, 'rb') as file:
            test_id = await self.dd.send_report(
                report = DefectDojoReport(
                    file = file,
                    scan_type = scan_type,
                    endpoint_id = endpoint_id,
                    engagement_id = engagement_id,
                    branch = branch,
                    report_name = report_name
                )
            )
            if test_id == None:
                self._log_err(f"[{project_id}] failed to upload report {file_path} - {scan_type}")
                return None
            
            self._log(f"[{project_id}] uploaded report {file_path} - {scan_type}: test_id = {test_id}")
            return test_id