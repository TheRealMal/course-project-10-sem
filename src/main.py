#!/usr/bin/env python3
import asyncio
import json
import os

from dotenv import load_dotenv
load_dotenv()

from modules.main import Main
from modules.config import ProjectConfig
from modules.db import Database
from modules.defectdojo import DefectDojo
from modules.git import Gitlab
from modules.scanner import ScannRunner
from modules.rocket import Rocket

CONFIG_PROJECTS_FILEPATH    = "config/projects.json"

async def main() -> None:
    dd_host     = os.getenv("DD_HOST")
    dd_token    = os.getenv("DD_TOKEN")
    git_host    = os.getenv("GIT_HOST")
    git_token   = os.getenv("GIT_TOKEN")
    db_url      = os.getenv("DB_CONNECT_URL")

    rocket_host = os.getenv("ROCKET_HOST")
    rocket_username = os.getenv("ROCKET_USERNAME")
    rocket_password = os.getenv("ROCKET_PASSWORD")
    rocket_chat_id = os.getenv("ROCKET_CHAT_ID")

    registries_credentials = os.getenv("REGISTRIES_CREDENTIALS")
    registries_credentials = json.loads(registries_credentials) if registries_credentials != "" else {}

    if not all([dd_host, dd_token, git_host, git_token, db_url, rocket_host, rocket_username, rocket_password, rocket_chat_id]):
        raise ValueError("environment variables needed: DD_HOST, DD_TOKEN, GIT_TOKEN, DB_CONNECT_URL, ROCKET_HOST, ROCKET_USERNAME, ROCKET_PASSWORD, ROCKET_CHAT_ID")
    
    projects_from_config = ProjectConfig.from_file(CONFIG_PROJECTS_FILEPATH)
    if len(projects_from_config) == 0:
        print("no projects to be scanned, exit")
        return

    rocket  = Rocket(rocket_host, rocket_username, rocket_password, rocket_chat_id)
    dd      = DefectDojo(dd_host, dd_token)
    gitlab  = Gitlab(git_host, git_token)
    scanner = ScannRunner(git_host, git_token, registries_credentials)
    db      = Database(db_url)
    await db.connect()

    m = Main(dd, gitlab, scanner, db, rocket)
    await m.sync_projects_with_db(projects_from_config)
    
    await m.scanner.load_scanners()
    await m.process_projects_from_db()
    await m.process_images_from_db()

    await db.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(e)
        exit(1)